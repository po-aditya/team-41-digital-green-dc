"""Settings. Everything can be overridden with environment variables."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PACK = Path(os.getenv("MEL_PACK_DIR", ROOT / "data" / "participant-pack"))
DATA = PACK / "data"
SCHEMAS = PACK / "json" / "schemas"
RULES_FILE = PACK / "json" / "rules" / "rules.json"
OUTCOMES_FILE = PACK / "json" / "rules" / "outcome_codes.json"
SCENARIOS = PACK / "json" / "scenarios"
OUT = Path(os.getenv("MEL_OUT_DIR", ROOT / "out"))
REPORTS = Path(os.getenv("MEL_REPORTS_DIR", ROOT / "reports"))

AWS_REGION = os.getenv("AWS_REGION", "us-west-2")
# Model choice stays behind these two names so it is easy to swap.
WRITER_MODEL = os.getenv("MEL_WRITER_MODEL", "us.anthropic.claude-sonnet-5-5")
CHECKER_MODEL = os.getenv("MEL_CHECKER_MODEL", "us.anthropic.claude-haiku-5-5")

# USD per 1M tokens, as "input,output". Unset means cost is not estimated:
# set these from the Bedrock pricing page for your models.
WRITER_PRICE = os.getenv("MEL_WRITER_PRICE")
CHECKER_PRICE = os.getenv("MEL_CHECKER_PRICE")

# A survey is scheduled only if the checker scores relevance at least this high.
MIN_RELEVANCE = float(os.getenv("MEL_MIN_RELEVANCE", "0.8"))
# How many insights are processed at once in a batch.
WORKERS = int(os.getenv("MEL_WORKERS", "8"))
