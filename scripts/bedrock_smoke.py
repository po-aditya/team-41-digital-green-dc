"""One minimal, paid Bedrock call to prove credentials and model access.

Sends a few-token prompt with maxTokens=16. Prints token usage, latency and
estimated cost. Refuses to run unless --yes is passed, so it is never
triggered by accident.

All configuration is checked BEFORE any AWS call: settings, region, pricing
file, then credentials. Errors are one line on stderr; secrets are never printed.

Exit codes: 0 success, 1 AWS/Bedrock call failed, 2 not confirmed or misconfigured.

Usage:
  python scripts/bedrock_smoke.py --yes [--model us.anthropic.claude-haiku-5-5]
"""

from __future__ import annotations

import argparse
import json
import sys

from botocore.exceptions import BotoCoreError, ClientError
from pydantic import ValidationError

from mel_agent.config import Settings
from mel_agent.llm import (
    BedrockConfigError,
    BedrockInvoker,
    PricingConfigError,
    PricingTable,
    credentials_available,
)

EXIT_OK, EXIT_CALL_FAILED, EXIT_CONFIG = 0, 1, 2


def _fail(msg: str, code: int) -> int:
    print(f"ERROR: {msg}", file=sys.stderr)
    return code


def _describe_settings_error(exc: ValidationError) -> str:
    # Field names and messages only; never echo the offending input values.
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

    if not settings.resolved_bedrock_region:
        return _fail(
            "no AWS region configured. Set MEL_BEDROCK_REGION (or AWS_REGION / AWS_DEFAULT_REGION), "
            "e.g. MEL_BEDROCK_REGION=us-west-2",
            EXIT_CONFIG,
        )

    try:
        pricing = PricingTable.load(settings.pricing_file)
    except PricingConfigError as exc:
        return _fail(f"{exc}. Regenerate with: python scripts/fetch_bedrock_pricing.py --region <region>", EXIT_CONFIG)

    model = args.model or settings.bedrock_model_id
    if pricing.price_for(model) is None:
        print(f"WARNING: no pricing entry for {model}; cost will be reported as null", file=sys.stderr)

    if not credentials_available(settings):
        return _fail(
            "no AWS credentials found by the default provider chain "
            "(environment, ~/.aws config/SSO, or IAM role)",
            EXIT_CONFIG,
        )

    invoker = BedrockInvoker(settings, pricing=pricing)
    try:
        result = invoker.converse("Reply with exactly one word: ok", model_id=model, max_tokens=16)
    except BedrockConfigError as exc:
        return _fail(str(exc), EXIT_CONFIG)
    except ClientError as exc:
        err = exc.response.get("Error", {})
        return _fail(f"Bedrock {err.get('Code')}: {err.get('Message')}", EXIT_CALL_FAILED)
    except BotoCoreError as exc:
        return _fail(f"Bedrock {type(exc).__name__}: {exc}", EXIT_CALL_FAILED)

    out = result.to_dict()
    out["region"] = invoker.client.meta.region_name
    print(json.dumps(out, indent=2))
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
