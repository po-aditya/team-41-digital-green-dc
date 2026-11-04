"""Paths and runtime configuration.

The participant-pack is treated as READ-ONLY input. Nothing in this project
writes to it. Override PARTICIPANT_PACK via the FARMERLOOP_PACK env var if the
pack lives elsewhere.
"""

from __future__ import annotations

import os
from pathlib import Path

# Repo root = two levels up from this file (src/farmerloop/config.py -> repo).
REPO_ROOT = Path(__file__).resolve().parents[2]

# Candidate pack locations, checked in order:
#   1. ../participant-pack        (standalone workshop layout)
#   2. ../data/participant-pack   (team repository layout)
_PACK_CANDIDATES = (
    REPO_ROOT.parent / "participant-pack",
    REPO_ROOT.parent / "data" / "participant-pack",
)


def _resolve_pack() -> Path:
    """FARMERLOOP_PACK wins if set; otherwise the first candidate that exists.

    If none exist we return the first candidate so the error message names a
    concrete path rather than silently picking an unrelated directory.
    """
    env = os.environ.get("FARMERLOOP_PACK")
    if env:
        return Path(env).resolve()
    for candidate in _PACK_CANDIDATES:
        if (candidate / "json" / "schemas").is_dir():
            return candidate.resolve()
    return _PACK_CANDIDATES[0].resolve()


PARTICIPANT_PACK = _resolve_pack()

# Data files (read-only).
DATA_DIR = PARTICIPANT_PACK / "data"
INSIGHTS_JSONL = DATA_DIR / "insights.jsonl"
GOLDEN_JSONL = DATA_DIR / "golden_set.jsonl"
FARMERS_CSV = DATA_DIR / "farmers.csv"
CROP_CALENDAR_CSV = DATA_DIR / "crop_calendar_bihar_rabi.csv"

# JSON schemas (read-only, authoritative delivery contract).
SCHEMA_DIR = PARTICIPANT_PACK / "json" / "schemas"
RULES_JSON = PARTICIPANT_PACK / "json" / "rules" / "rules.json"
OUTCOME_CODES_JSON = PARTICIPANT_PACK / "json" / "rules" / "outcome_codes.json"

# India Standard Time offset, used everywhere timestamps are built.
IST_OFFSET = "+05:30"

# Bedrock defaults. us-west-2 confirmed to expose these inference profiles.
# Nova Lite is cheap, fast and multilingual; Claude Haiku is the documented
# alternative. Both are reachable via the "us." cross-region inference profile.
BEDROCK_REGION = os.environ.get("AWS_REGION", "us-west-2")
BEDROCK_MODEL_ID = os.environ.get(
    "FARMERLOOP_BEDROCK_MODEL", "us.amazon.nova-lite-v1:0"
)
