"""Read-only access to json/rules/outcome_codes.json.

Every status, retry decision, retry delay, cap rule and allowed channel used
when building a response record comes from this file. Nothing here is copied
from the example response records.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from . import config

CHANNELS = ("app", "web", "whatsapp", "telegram", "voice")
SHEET_CHANNELS = frozenset({"app", "web"})  # surveys shown as a bottom sheet


class ResponseConfigError(ValueError):
    """Developer/program error: an impossible or inconsistent request.

    Distinct from invalid FARMER input, which is a normal outcome
    (status invalid_input) and never raises.
    """


@dataclass(frozen=True)
class OutcomeRule:
    """What the official rules say about one outcome code."""

    code: str | None          # failure_code written to the record (None for successes)
    status: str
    retry_decision: str
    retry_after_minutes: int | None
    counts_toward_cap: bool
    channels: frozenset[str]   # channels this code can occur on
    sheet_outcome: str | None = None  # only set by the rules for sheet cases


@lru_cache(maxsize=1)
def _raw() -> dict[str, Any]:
    with config.OUTCOME_CODES_JSON.open(encoding="utf-8") as fh:
        return json.load(fh)


def success_rule(status: str) -> OutcomeRule:
    """Rule for completed / partial / negative_outcome."""
    entry = _raw()["success"].get(status)
    if entry is None:
        raise ResponseConfigError(f"{status!r} is not a success status")
    return OutcomeRule(
        code=None,
        status=status,
        retry_decision=entry["retry_decision"],
        retry_after_minutes=None,
        counts_toward_cap=entry["counts_toward_cap"],
        channels=frozenset(CHANNELS),
    )


def failure_rule(code: str) -> OutcomeRule:
    entry = _raw()["failures"].get(code)
    if entry is None:
        raise ResponseConfigError(f"{code!r} is not a known failure code")
    return OutcomeRule(
        code=code,
        status=entry["status"],
        retry_decision=entry["retry_decision"],
        retry_after_minutes=entry["retry_after_minutes"],
        counts_toward_cap=entry["counts_toward_cap"],
        channels=frozenset(entry["channels"]),
    )


def sheet_case_rule(case: str) -> OutcomeRule:
    """Rule for sheet_closed_partway / sheet_interrupted (app and web only)."""
    entry = _raw()["sheet_cases"].get(case)
    if entry is None:
        raise ResponseConfigError(f"{case!r} is not a known sheet case")
    return OutcomeRule(
        code=None,  # sheet cases are partial successes, not failures
        status=entry["status"],
        retry_decision=entry["retry_decision"],
        retry_after_minutes=entry["retry_after_minutes"],
        counts_toward_cap=entry["counts_toward_cap"],
        channels=SHEET_CHANNELS,
        sheet_outcome=entry["sheet_outcome"],
    )


def failure_codes() -> frozenset[str]:
    return frozenset(_raw()["failures"])


def sheet_cases() -> frozenset[str]:
    return frozenset(_raw()["sheet_cases"])


def event_rule(event: str) -> OutcomeRule:
    """Look up an external channel/server event (a failure code or sheet case)."""
    if event in _raw()["sheet_cases"]:
        return sheet_case_rule(event)
    return failure_rule(event)


def not_applicable(channel: str, code: str) -> str | None:
    """The official reason a channel/code pair cannot happen, if any."""
    return _raw()["not_applicable"].get(f"{channel}/{code}")
