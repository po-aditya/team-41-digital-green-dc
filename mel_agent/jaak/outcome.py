"""Status, completeness and follow-up derivation (Req 12.1-12.3, 12.5, 12.7, 12.9, 12.10, 13.1-13.10).

Pure functions over small inputs, shared by the session (task 5.2) and the
record builder (task 6.2).

Shape
-----
``ItemOutcome`` is the resolved state of one Survey Item:

* ``item_id``   Survey Item id;
* ``result``    ``answered | skipped | invalid | not_reached | discarded``;
* ``value``     accepted answer (option value ``str`` or scale ``int``), else ``None``;
* ``attempts``  times the Item was asked;
* ``raw_input`` the farmer's raw text, kept for the record. Never read here.

Follow-up reasons come from Survey fields and accepted values only. Nothing
else (raw input, rationale, Insight fields) is read.

Failure codes and their ``outcome_codes.json`` rows are wired in task 11.1.
Here a failure is just its already-resolved response status string.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

from mel_agent.jaak.models import Survey

__all__ = [
    "ItemOutcome",
    "follow_up_reasons",
    "follow_up_fields",
    "is_complete",
    "derive_status",
    "success_fields",
]


@dataclass(frozen=True)
class ItemOutcome:
    item_id: str
    result: str
    value: Optional[str | int] = None
    attempts: int = 0
    raw_input: Optional[str] = None


def follow_up_reasons(survey: Survey, item_outcomes: Sequence[ItemOutcome]) -> list[str]:
    """Reasons triggered by accepted answers, in Survey order, first occurrence kept."""
    by_id = {o.item_id: o for o in item_outcomes}
    reasons: list[str] = []
    for item in survey.items:
        outcome = by_id.get(item.item_id)
        if outcome is None or outcome.result != "answered" or outcome.value is None:
            continue
        reason: Optional[str] = None
        if item.type == "survey-scale":
            value = outcome.value
            if (
                isinstance(value, int)
                and not isinstance(value, bool)
                and item.follow_up_at_or_below is not None
                and item.follow_up_reason
                and value <= item.follow_up_at_or_below
            ):
                reason = item.follow_up_reason
        else:
            for option in item.options or []:
                if option.value == outcome.value:
                    reason = option.follow_up or None
                    break
        if reason and reason not in reasons:
            reasons.append(reason)
    return reasons


def follow_up_fields(status: str, reasons: Sequence[str], failure: bool = False) -> tuple[bool, list[str]]:
    """``(needs_follow_up, follow_up_reasons)``. A failure outcome discards the reasons (Req 13.8).

    ``failure`` is true for any status other than completed/partial/negative_outcome.
    """
    if failure or status not in ("completed", "partial", "negative_outcome"):
        return False, []
    out = list(reasons)
    return bool(out), out


def is_complete(item_outcomes: Sequence[ItemOutcome]) -> bool:
    """True iff every Item is answered (Req 12.9)."""
    return bool(item_outcomes) and all(o.result == "answered" for o in item_outcomes)


def derive_status(
    item_outcomes: Sequence[ItemOutcome],
    reasons: Sequence[str],
    failure: Optional[str] = None,
) -> str:
    """Precedence: failure status, ``negative_outcome``, ``partial``, ``completed`` (Req 12.10).

    ``failure`` is the response status of a failure outcome (e.g. ``expired``), or ``None``.
    ``negative_outcome`` and ``partial`` need at least one answered Item.
    """
    if failure is not None:
        return failure
    answered = sum(1 for o in item_outcomes if o.result == "answered")
    if answered >= 1 and reasons:
        return "negative_outcome"
    if answered >= 1 and not is_complete(item_outcomes):
        return "partial"
    if is_complete(item_outcomes):
        return "completed"
    raise ValueError("no answered Item and no failure status")


def success_fields(status: str) -> dict:
    """Retry and reply fields for a success status (Req 12.7)."""
    if status not in ("completed", "partial", "negative_outcome"):
        raise ValueError("not a success status")
    return {
        "retry_decision": "none",
        "retry_after_minutes": None,
        "counts_toward_cap": True,
        "farmerchat_reply": None,
    }
