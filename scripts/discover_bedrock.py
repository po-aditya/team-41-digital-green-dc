"""List Bedrock inference profiles and text models in the configured region.

Free, read-only control-plane calls. No inference is performed.

Usage:
  python scripts/discover_bedrock.py [--filter anthropic] [--json]
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict

from botocore.exceptions import BotoCoreError, ClientError

from mel_agent.config import get_settings
from mel_agent.llm import BedrockConfigError, discover


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--filter", default=None, help="substring to match in ids, e.g. 'anthropic'")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    try:
        result = discover(get_settings(), provider_filter=args.filter)
    except BedrockConfigError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except ClientError as exc:
        err = exc.response.get("Error", {})
        print(f"ERROR: Bedrock {err.get('Code')}: {err.get('Message')}", file=sys.stderr)
        return 1
    except BotoCoreError as exc:
        print(f"ERROR: AWS {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(asdict(result), indent=2))
        return 0
    print(f"Region: {result.region}")
    print(f"\nInference profiles ({len(result.inference_profiles)}):")
    for p in result.inference_profiles:
        print(f"  {p['id']:<55} {p['status']}")
    print(f"\nText foundation models ({len(result.foundation_models)}):")
    for m in result.foundation_models:
        print(f"  {m['id']:<55} {','.join(m['inference_types']):<30} {m['lifecycle']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
