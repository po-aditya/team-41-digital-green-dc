"""One minimal, paid Bedrock call to prove credentials and model access.

Goes through the same gates as the application: explicit paid-inference
authorisation, pricing for the model, a ledger reservation under the cutoff,
and fail-closed usage handling. There is no way around them from here.

Order of checks (all before any credential lookup or AWS call):
  --yes -> settings -> MEL_ALLOW_PAID_INFERENCE -> region -> pricing file -> model priced
  -> ledger state ok -> headroom for this exact call (dry-run reservation) -> credentials
  -> one Converse call through BudgetedInvoker (SDK retries off; reserve -> settle | unresolved)

Exit codes: 0 success, 1 AWS/Bedrock call failed, 2 not confirmed / not authorised / misconfigured / no budget.

Usage:
  MEL_ALLOW_PAID_INFERENCE=true python scripts/bedrock_smoke.py --yes [--model us.anthropic.claude-haiku-5-5]
"""

from __future__ import annotations

import argparse
import json
import sys

from botocore.exceptions import BotoCoreError, ClientError
from pydantic import ValidationError

from mel_agent.budget import BudgetController, BudgetError, BudgetExceeded, BudgetUnavailable, PaidInferenceDisabled
from mel_agent.config import Settings
from mel_agent.llm import BedrockConfigError, BedrockInvoker, PricingConfigError, PricingTable, credentials_available
from mel_agent.llm.budgeted import BudgetedInvoker, PaidCallFailed
from mel_agent.store import Store

EXIT_OK, EXIT_CALL_FAILED, EXIT_CONFIG = 0, 1, 2
PROMPT = "Reply with exactly one word: ok"
MAX_TOKENS = 16


def _fail(msg: str, code: int) -> int:
    print(f"ERROR: {msg}", file=sys.stderr)
    return code


def _describe_settings_error(exc: ValidationError) -> str:
    parts = []
    for err in exc.errors(include_input=False, include_url=False):
        field = ".".join(str(p) for p in err["loc"]) or "settings"
        env = f"MEL_{field.upper()}" if err["loc"] else "MEL_* settings"
        parts.append(f"{env}: {err['msg']}")
    return "invalid configuration: " + "; ".join(parts)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--yes", action="store_true", help="confirm one paid inference call")
    ap.add_argument("--model", default=None)
    args = ap.parse_args(argv)
    if not args.yes:
        return _fail("refusing to make a paid call without --yes", EXIT_CONFIG)

    try:
        settings = Settings()
    except ValidationError as exc:
        return _fail(_describe_settings_error(exc), EXIT_CONFIG)

    if not settings.allow_paid_inference:
        return _fail("paid inference is disabled; set MEL_ALLOW_PAID_INFERENCE=true to authorise this call", EXIT_CONFIG)

    if not settings.resolved_bedrock_region:
        return _fail("no AWS region configured. Set MEL_BEDROCK_REGION (or AWS_REGION / AWS_DEFAULT_REGION), e.g. MEL_BEDROCK_REGION=us-west-2", EXIT_CONFIG)

    try:
        pricing = PricingTable.load(settings.pricing_file)
    except PricingConfigError as exc:
        return _fail(f"{exc}. Regenerate with: python scripts/fetch_bedrock_pricing.py --region <region>", EXIT_CONFIG)

    model = args.model or settings.bedrock_model_id
    if pricing.price_for(model) is None:
        return _fail("no pricing entry for the requested model; refusing (cost could not be metered)", EXIT_CONFIG)

    try:
        store = Store.from_url(settings.database_url)
        controller = BudgetController(store, settings, pricing)
        status = controller.status()
    except BudgetError as exc:
        return _fail(f"budget ledger unavailable: {exc}", EXIT_CONFIG)
    if status.state != "ok":
        return _fail(f"budget state is '{status.state}' (committed ${status.committed_usd:.4f} of ${status.cutoff_usd:.2f} cutoff); refusing", EXIT_CONFIG)
    try:
        # Financial feasibility of THIS call is established before any credential lookup.
        controller.check_headroom(model, controller.estimate_tokens(PROMPT), MAX_TOKENS, attempts=1)
    except BudgetExceeded as exc:
        return _fail(str(exc), EXIT_CONFIG)
    except BudgetUnavailable as exc:
        return _fail(f"budget check failed: {exc}", EXIT_CONFIG)

    if not credentials_available(settings):
        return _fail("no AWS credentials found by the default provider chain (environment, ~/.aws config/SSO, or IAM role)", EXIT_CONFIG)

    invoker = BudgetedInvoker(BedrockInvoker(settings, pricing=pricing), controller)
    try:
        result = invoker.converse(PROMPT, model_id=model, max_tokens=MAX_TOKENS)
    except PaidInferenceDisabled as exc:
        return _fail(str(exc), EXIT_CONFIG)
    except BudgetExceeded as exc:
        return _fail(str(exc), EXIT_CONFIG)
    except BudgetUnavailable as exc:
        return _fail(f"budget check failed: {exc}", EXIT_CONFIG)
    except BedrockConfigError as exc:
        return _fail(str(exc), EXIT_CONFIG)
    except PaidCallFailed as exc:
        return _fail(f"Bedrock call failed on every attempt: {type(exc.last).__name__}", EXIT_CALL_FAILED)
    except ClientError as exc:
        err = exc.response.get("Error", {})
        return _fail(f"Bedrock {err.get('Code')}: {err.get('Message')}", EXIT_CALL_FAILED)
    except BotoCoreError as exc:
        return _fail(f"Bedrock {type(exc).__name__}: {exc}", EXIT_CALL_FAILED)

    out = result.to_dict()
    out["region"] = invoker.invoker.client.meta.region_name
    out["budget"] = controller.status().to_dict()
    if not result.usage_verified:
        out["warning"] = "response carried no verifiable usage; the reservation stays committed until reconciled"
    print(json.dumps(out, indent=2))
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
