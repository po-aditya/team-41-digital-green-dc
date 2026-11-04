"""BedrockInvoker wrapped in the budget controller. The only sanctioned path to paid inference.

Operation order for every paid request (review-3 finding 4, review-4 finding 3)
  1. ownership check (``may_continue``), if the caller supplied one;
  2. authorisation, pricing and headroom, all inside ``controller.reserve`` (which also
     refuses while too many reservations are unresolved);
  3. only then is the credential-bearing boto3 client constructed or touched (this can be
     slow: lazy construction, credential providers);
  4. ownership is checked AGAIN, immediately before the request is submitted. Lost
     ownership here releases the unused reservation (nothing was sent) and raises
     OwnershipLost without touching the replacement worker's work;
  5. the request is sent;
  6. the reservation is settled, released or kept as unresolved.
A rejected request therefore performs zero client constructions, credential lookups
or inference calls, and a superseded worker never submits a request.

Retry metadata has three states (``retry_attempts_in``): verified zero, verified
positive, unknown (missing or malformed envelope/field/type). Only VERIFIED ZERO allows
the ordinary classification below; verified positive and unknown are both unresolved,
on errors and on successes alike, so malformed metadata can never restore headroom.

Accounting boundary: ONE application attempt = ONE request on the wire = ONE
reservation with ONE recorded outcome. The paid client is built with the SDK retry
budget set to a single attempt and the wrapper refuses to run on any other client, so
botocore never re-sends a paid request behind our back.

Error-classification policy (review-3 finding 1). A reservation is RELEASED only when
the response definitively establishes that no model work happened, which requires
BOTH a well-formed ``RetryAttempts == 0`` AND an error code in one of the two
"rejected before inference" sets below. Everything else is UNRESOLVED: the estimate
stays committed until a human reconciles it against the AWS bill.

  released, retryable      ThrottlingException, TooManyRequestsException,
                           ServiceQuotaExceededException, ModelNotReadyException
  released, not retryable  ValidationException, AccessDeniedException,
                           ResourceNotFoundException, UnrecognizedClientException,
                           InvalidSignatureException, ExpiredTokenException
  unresolved, stop         ModelErrorException, ModelTimeoutException,
                           ModelStreamErrorException, InternalServerException,
                           ServiceUnavailableException, any unknown code, any error or
                           success whose RetryAttempts is unknown (missing/malformed) or > 0,
                           a success without verifiable usage, timeouts and connection
                           loss (retried only with MEL_BEDROCK_PAID_RETRY_AFTER_TIMEOUT),
                           any other exception.

Retries are explicit application attempts (``bedrock_paid_app_attempts``), each
reserved before it is sent and each preceded by the ownership check, so a worker
that has lost its claim cannot start another paid request (review-3 finding 5).
Unresolved reservations are durable ledger rows; a restart does not forget them, and
``budget_max_unresolved`` stops new paid attempts while too many are outstanding.
"""

from __future__ import annotations

from typing import Callable

from botocore.exceptions import BotoCoreError, ClientError, ConnectTimeoutError, EndpointConnectionError, ReadTimeoutError

from mel_agent.budget.controller import BudgetController, BudgetUnavailable, Reservation
from mel_agent.llm.bedrock import BedrockInvoker, InferenceResult, retry_attempts_in, sdk_total_max_attempts

# Rejected before any model work (not billed) and worth another explicit attempt.
RELEASE_RETRYABLE = frozenset({"ThrottlingException", "TooManyRequestsException", "ServiceQuotaExceededException", "ModelNotReadyException"})
# Rejected before any model work (not billed) and pointless to retry.
RELEASE_PERMANENT = frozenset({"ValidationException", "AccessDeniedException", "ResourceNotFoundException", "UnrecognizedClientException",
                               "InvalidSignatureException", "ExpiredTokenException"})
# Documented examples of "model work may have happened": listed for the policy table and tests; any code
# that is not in the two sets above is treated the same way.
UNRESOLVED_EXAMPLES = frozenset({"ModelErrorException", "ModelTimeoutException", "ModelStreamErrorException", "InternalServerException",
                                 "ServiceUnavailableException"})

# Backwards-compatible names used by earlier tests and docs.
TRANSIENT_NOT_BILLED = RELEASE_RETRYABLE
PERMANENT_NOT_BILLED = RELEASE_PERMANENT


def classify_client_error(code: str, retry_attempts: int | None) -> str:
    """'release_retry' | 'release_stop' | 'unresolved' for a ClientError, per the module policy."""
    if retry_attempts is None or retry_attempts > 0:
        return "unresolved"
    if code in RELEASE_RETRYABLE:
        return "release_retry"
    if code in RELEASE_PERMANENT:
        return "release_stop"
    return "unresolved"


class PaidCallFailed(RuntimeError):
    """All application attempts failed; ``last`` holds the final exception."""

    def __init__(self, message: str, last: BaseException) -> None:
        super().__init__(message)
        self.last = last


class OwnershipLost(RuntimeError):
    """The caller no longer owns the work item; no new paid request was started."""


class BudgetedInvoker:
    def __init__(self, invoker: BedrockInvoker, controller: BudgetController, app_attempts: int | None = None,
                 retry_after_timeout: bool | None = None) -> None:
        self.invoker = invoker
        self.controller = controller
        settings = invoker.settings
        self.app_attempts = int(app_attempts if app_attempts is not None else settings.bedrock_paid_app_attempts)
        self.retry_after_timeout = bool(settings.bedrock_paid_retry_after_timeout if retry_after_timeout is None else retry_after_timeout)
        if invoker._client is None:
            invoker.sdk_total_max_attempts = 1  # the paid client, when it is eventually built, gets no SDK retries

    def _check_client(self) -> None:
        """Build/touch the client (step 3) and refuse one that could retry behind our back."""
        attempts = sdk_total_max_attempts(self.invoker.client)
        if attempts != 1:
            raise BudgetUnavailable("paid inference requires a client with SDK retries disabled (total_max_attempts=1); refusing")

    def _unresolved(self, reservation: Reservation, reason: str) -> None:
        self.controller.mark_unresolved(reservation, reason)

    def converse(self, prompt: str, *, system: str | None = None, model_id: str | None = None,
                 max_tokens: int | None = None, temperature: float | None = None,
                 may_continue: Callable[[], bool] | None = None) -> InferenceResult:
        model = model_id or self.invoker.settings.bedrock_model_id
        max_out = max_tokens or self.invoker.settings.bedrock_max_tokens
        input_tokens = self.controller.estimate_tokens((system or "") + prompt)
        last_exc: BaseException | None = None
        for attempt in range(1, self.app_attempts + 1):
            # 1. ownership: a superseded worker must not start a new paid request (not even a retry)
            if may_continue is not None and not may_continue():
                raise OwnershipLost("work item no longer owned; refusing to start a paid request")
            # 2. authorisation, pricing, unresolved cap and headroom, recorded atomically
            reservation = self.controller.reserve(model, input_tokens, max_out, attempts=1)
            # 3. only now the credential-bearing client
            try:
                self._check_client()
            except BaseException:
                self.controller.release(reservation, "client could not be prepared; no request was sent")
                raise
            # 4. ownership again, right before submitting: client construction may have been slow enough for the
            #    lease to lapse and a replacement worker to take over. Nothing was sent, so the money comes back.
            if may_continue is not None and not may_continue():
                self.controller.release(reservation, "ownership lost before the request was sent")
                raise OwnershipLost("work item taken over during client preparation; no request was sent")
            # 5. the request
            try:
                result = self.invoker.converse(prompt, system=system, model_id=model, max_tokens=max_out, temperature=temperature)
            except ClientError as exc:
                last_exc = exc
                code = str(exc.response.get("Error", {}).get("Code", "")) or "UnknownClientError"
                reported = retry_attempts_in(exc.response)
                verdict = classify_client_error(code, reported)
                if verdict == "unresolved":
                    why = ("retry metadata unknown or malformed" if reported is None else f"{reported} SDK transport retries reported" if reported
                           else "error during or after model processing")
                    self._unresolved(reservation, f"{code}: {why}; billing unknown")
                    raise
                self.controller.release(reservation, f"rejected before inference: {code}")
                if verdict == "release_retry" and attempt < self.app_attempts:
                    continue
                if verdict == "release_retry":
                    raise PaidCallFailed(f"{code} on every application attempt", exc) from exc
                raise
            except (ReadTimeoutError, ConnectTimeoutError, EndpointConnectionError) as exc:
                last_exc = exc
                self._unresolved(reservation, "timeout or connection failure; request may have been billed")
                if self.retry_after_timeout and attempt < self.app_attempts:
                    continue
                raise
            except BotoCoreError:
                self._unresolved(reservation, "botocore error; billing unknown")
                raise
            except BaseException:
                self._unresolved(reservation, "unexpected failure during paid call")
                raise
            # 6. outcome: only a VERIFIED zero retry count plus verified usage settles
            reported = result.retry_attempts
            if reported is None or reported > 0:
                why = "retry metadata unknown or malformed" if reported is None else f"SDK reported {reported} transport retries on a success"
                self._unresolved(reservation, why)
                result.estimated_cost_usd = float(reservation.estimated_usd)
                return result
            if result.usage is None:
                self._unresolved(reservation, "response carried no verifiable usage")
                result.estimated_cost_usd = float(reservation.estimated_usd)
                return result
            result.estimated_cost_usd = self.controller.settle(reservation, result.usage)
            return result
        raise PaidCallFailed("no application attempt succeeded", last_exc or RuntimeError("no attempts"))
