"""Error types for the JAAK core engine.

Errors never carry answer text, farmer names, or library messages that echo
values. ``str(error)`` carries the boundary, JSON paths and keyword reasons only.
"""

from __future__ import annotations

from typing import Iterable


class JaakError(Exception):
    """Base class for every engine error.

    ``logging_failed`` is set to True when the log sink raised while the
    Rejection_Log entry for this error was being written (Req 19.6).
    """

    logging_failed: bool = False

    def __init__(self, message: str = "", *, logging_failed: bool = False) -> None:
        super().__init__(message)
        self.logging_failed = logging_failed


class InputRejected(JaakError):
    """An input boundary rejected its payload.

    ``boundary`` is one of ``survey_input``, ``farmer_record_input`` or
    ``survey_farmer_pair``. ``failures`` is a tuple of ``(json_path, reason)``
    pairs with keyword reasons only.
    """

    def __init__(
        self,
        boundary: str,
        failures: Iterable[tuple[str, str]] = (),
        *,
        logging_failed: bool = False,
    ) -> None:
        self.boundary = boundary
        self.failures: tuple[tuple[str, str], ...] = tuple(
            (str(p), str(r)) for p, r in failures
        )
        detail = "; ".join(f"{p}: {r}" for p, r in self.failures)
        message = f"input rejected at {boundary}" + (f": {detail}" if detail else "")
        super().__init__(message, logging_failed=logging_failed)


class InvalidRequest(JaakError):
    """A call parameter or transcribed answer failed validation.

    ``boundary`` names the rejected input (``call_parameters`` or
    ``transcribed_answer_input``).
    """

    def __init__(
        self,
        message: str = "",
        *,
        boundary: str = "call_parameters",
        failures: Iterable[tuple[str, str]] = (),
        logging_failed: bool = False,
    ) -> None:
        self.boundary = boundary
        self.failures: tuple[tuple[str, str], ...] = tuple(
            (str(p), str(r)) for p, r in failures
        )
        super().__init__(message or f"invalid request at {boundary}", logging_failed=logging_failed)


class LanguageUnavailable(JaakError):
    """The session language is not in the template set (Req 2.5, 6.8)."""

    def __init__(self, language: str = "", *, logging_failed: bool = False) -> None:
        self.language = language
        super().__init__(
            f"language unavailable: {language}" if language else "language unavailable",
            logging_failed=logging_failed,
        )


class GreetingFailed(JaakError):
    """The greeting could not be rendered; no session is created (Req 2.6)."""


class SurveyTextMissing(JaakError):
    """A prompt or label was empty or missing at render time (Req 6.7)."""


class TemplateError(JaakError):
    """A template violates a validation rule at load (Req 7.7)."""

    def __init__(self, template_id: str, rule: str) -> None:
        self.template_id = template_id
        self.rule = rule
        super().__init__(f"template {template_id} violates rule {rule}")


class UnknownSession(JaakError):
    """The session_id is not known to the engine."""


class SessionFinalised(JaakError):
    """The session has been finalised and accepts no further calls."""


class OutOfOrder(JaakError):
    """The call is not allowed in the current session state."""


class NotEnded(OutOfOrder):
    """``get_response`` was called before the session ended."""


class TurnsPending(OutOfOrder):
    """``get_response`` was called while queued Turns remain untaken."""


class EventRejected(JaakError):
    """A caller event code is unlisted for voice or not caller-reportable (Req 11.14)."""

    boundary = "caller_event_input"

    def __init__(self, message: str = "", *, logging_failed: bool = False) -> None:
        super().__init__(message or "event rejected", logging_failed=logging_failed)


class RecordInvalid(JaakError):
    """The built Response_Record failed validation (Req 1.6).

    ``failures`` holds ``(json_path, reason)`` pairs; no record is returned.
    """

    boundary = "response_record_output"

    def __init__(
        self,
        failures: Iterable[tuple[str, str]] = (),
        *,
        logging_failed: bool = False,
    ) -> None:
        self.failures: tuple[tuple[str, str], ...] = tuple(
            (str(p), str(r)) for p, r in failures
        )
        detail = "; ".join(f"{p}: {r}" for p, r in self.failures)
        super().__init__(
            f"record invalid at {self.boundary}" + (f": {detail}" if detail else ""),
            logging_failed=logging_failed,
        )


class RecordUnavailable(JaakError):
    """The Response_Record could not be built, so none is available (Req 1.6).

    Raised by ``get_response`` on calls after a ``RecordInvalid`` for the same session.
    """


class ConfigError(JaakError):
    """Configuration problem, e.g. unreadable or forbidden name copy path (Req 4.7)."""

    def __init__(self, message: str = "", *, path: str | None = None, file: str | None = None) -> None:
        self.path = path
        self.file = file
        super().__init__(message or "configuration error")
