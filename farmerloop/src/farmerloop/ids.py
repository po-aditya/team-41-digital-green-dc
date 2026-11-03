"""Deterministic identifier helpers.

IDs are derived deterministically (UUIDv5) from stable inputs so the same
insight always produces the same survey/handoff/flow ids. This keeps the
pipeline reproducible and testable without a database.
"""

from __future__ import annotations

import uuid

# Fixed namespace for the hackathon campaign (any constant UUID works).
_NAMESPACE = uuid.UUID("283df456-256d-5d97-912f-1a6c4fdde6d0")

# From rules.json farmerchat_flow.campaign_name.
CAMPAIGN_NAME = "mel-hackathon-rabi-2026"
ORG_ID = "org.farmerchat"

# 10 digits = the schema maximum (^...[0-9]{5,10}$). With a ~9e9 value space,
# collision probability across 6,999 ids is negligible (< 3e-6 by birthday
# approximation), versus ~20%+ at 5 digits. Verified empirically by
# tests/test_ids.py and scripts/verify_ids.py.
_ID_DIGITS = 10


def _digits(seed: str, n: int) -> str:
    """Stable n-digit number derived from a seed (never all-zero prefix loss)."""
    h = uuid.uuid5(_NAMESPACE, seed).int
    mod = 10 ** n
    val = h % mod
    # Avoid a leading zero so the value always has exactly n digits.
    if val < 10 ** (n - 1):
        val += 10 ** (n - 1)
    return str(val)


def survey_id(insight_id: str) -> str:
    """S-NNNNNNNNNN (10 digits) derived from the insight id. Matches ^S-[0-9]{5,10}$."""
    return f"S-{_digits(f'survey:{insight_id}', _ID_DIGITS)}"


def handoff_id(survey_id_value: str) -> str:
    """H-NNNNNNNNNN (10 digits) derived from the survey id. Matches ^H-[0-9]{5,10}$."""
    return f"H-{_digits(f'handoff:{survey_id_value}', _ID_DIGITS)}"


def flow_key(survey_id_value: str) -> str:
    """mel_<survey_id_lower> with '-' -> '_'. Matches ^[a-z][a-z0-9_]{1,63}$."""
    return "mel_" + survey_id_value.lower().replace("-", "_")


def campaign_id() -> str:
    """Stable campaign UUID derived from the campaign name."""
    return str(uuid.uuid5(_NAMESPACE, f"campaign:{CAMPAIGN_NAME}"))


def flow_id(survey_id_value: str) -> str:
    """Stable per-survey flow UUID (the id in /v1/surveys/{flow_id}/responses)."""
    return str(uuid.uuid5(_NAMESPACE, f"flow:{survey_id_value}"))
