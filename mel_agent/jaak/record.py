"""Response_Record builder and final output validation (Req 1.5, 1.6, 12, 15).

``build_record`` is pure apart from the one log write on failure. It receives
only the validated Survey, the resolved ``ItemOutcome`` list, call parameters
and the engine clock. It never receives ``farmer_name``, ``state``,
``district`` or Unclear text, so it cannot write them (Req 4.6, 17.4).

The record is checked against ``data.validator("response")`` and the Pydantic
``ResponseRecord``. On any failure one Rejection_Log entry is written, then
``RecordInvalid`` is raised and nothing is returned (Req 1.6).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Sequence

from pydantic import ValidationError

from .. import data, rules
from .boundary import _dedupe, _emit, _pointer, _pydantic_failures
from .errors import RecordInvalid
from .logs import LogSink
from .models import CallTimes, ResponseRecord, Survey
from .outcome import (
    ItemOutcome,
    derive_status,
    follow_up_fields,
    follow_up_reasons,
    is_complete,
    success_fields,
)

__all__ = ["FailureInfo", "build_record", "RAW_INPUT_MAX"]

RAW_INPUT_MAX = 256
BOUNDARY = "response_record_output"


@dataclass(frozen=True)
class FailureInfo:
    """Failure-outcome fields, copied by the engine from ``outcome_codes.json`` (task 11.1)."""

    failure_code: str
    status: str
    retry_decision: str
    retry_after_minutes: Optional[int]
    counts_toward_cap: bool
    answered_by: Optional[str] = None  # override, e.g. reported id for identity_mismatch
    raw_event: Optional[str] = None


def _ts(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError("naive datetime")
    return rules.fmt_ts(dt)


def _reject(sink: LogSink, survey: Survey, failures) -> RecordInvalid:
    failures = _dedupe(failures)
    entry = {
        "event": "rejection",
        "level": "reject",
        "boundary": BOUNDARY,
        "survey_id": survey.survey_id,
        "farmer_id": survey.farmer_id,
        "failures": [{"path": p, "reason": r} for p, r in failures],
    }
    failed = _emit(sink, entry)
    return RecordInvalid(failures, logging_failed=failed)


def build_record(
    survey: Survey,
    item_outcomes: Sequence[ItemOutcome],
    *,
    delivery_attempt: int,
    recorded_at: datetime,
    log: LogSink,
    answered_at: Optional[datetime] = None,
    call_times: Optional[CallTimes] = None,
    failure: Optional[FailureInfo] = None,
) -> dict:
    """Build and validate one Response_Record. Raises ``RecordInvalid``; never returns a bad record."""
    try:
        record = _assemble(
            survey, list(item_outcomes), delivery_attempt, recorded_at, answered_at, call_times, failure
        )
    except Exception:  # noqa: BLE001 - any assembly problem is an invalid record, no text echoed
        raise _reject(log, survey, [("/", "type")]) from None

    failures = [
        (_pointer(e.absolute_path) if e.absolute_path else "/", str(e.validator))
        for e in data.validator("response").iter_errors(record)
    ]
    try:
        ResponseRecord.model_validate(json.loads(json.dumps(record)))
    except ValidationError as exc:
        failures.extend(_pydantic_failures(exc))
    if failures:
        raise _reject(log, survey, failures)
    return record


def _assemble(
    survey: Survey,
    outcomes: list[ItemOutcome],
    delivery_attempt: int,
    recorded_at: datetime,
    answered_at: Optional[datetime],
    call_times: Optional[CallTimes],
    failure: Optional[FailureInfo],
) -> dict:
    by_id = {o.item_id: o for o in outcomes}
    if len(by_id) != len(outcomes) or [i.item_id for i in survey.items] != [o.item_id for o in outcomes]:
        raise ValueError("outcomes do not match survey items")

    reasons = follow_up_reasons(survey, outcomes)
    status = derive_status(outcomes, reasons, failure.status if failure else None)
    needs, kept_reasons = follow_up_fields(status, reasons, failure=failure is not None)
    any_answered = any(o.result == "answered" for o in outcomes)

    answers: dict = {}
    items: list[dict] = []
    for item in survey.items:
        o = by_id[item.item_id]
        answered = o.result == "answered"
        if answered:
            answers[item.item_id] = o.value
        items.append(
            {
                "item_id": item.item_id,
                "item_type": item.type,
                "result": o.result,
                "value": o.value if answered else None,
                "raw_input": o.raw_input[:RAW_INPUT_MAX] if answered and o.raw_input is not None else None,
                "input_kind": "speech" if answered else None,
                "attempts": o.attempts,
            }
        )

    ct = call_times or CallTimes()
    if any_answered:
        answered_ts = _ts(answered_at if answered_at is not None else recorded_at)
    else:
        answered_ts = None

    if failure is not None:
        flow = {
            "failure_code": failure.failure_code,
            "retry_decision": failure.retry_decision,
            "retry_after_minutes": failure.retry_after_minutes,
            "counts_toward_cap": failure.counts_toward_cap,
            "farmerchat_reply": None,
        }
        raw_event = failure.raw_event[:RAW_INPUT_MAX] if failure.raw_event is not None else None
        answered_by = failure.answered_by
        if answered_by is None and any_answered:
            answered_by = survey.farmer_id
    else:
        flow = {"failure_code": None, **success_fields(status)}
        raw_event = None
        answered_by = survey.farmer_id if any_answered else None

    return {
        "response_key": f"rk-{survey.survey_id}-voice-{delivery_attempt}",
        "survey_id": survey.survey_id,
        "farmer_id": survey.farmer_id,
        "source_insight_ids": list(survey.source_insight_ids),
        "channel": "voice",
        "language": survey.language,
        "status": status,
        "failure_code": flow["failure_code"],
        "sheet_outcome": None,
        "answers": answers,
        "items": items,
        "complete": is_complete(outcomes),
        "delivery_attempt": delivery_attempt,
        "timestamps": {
            "sent": _ts(ct.sent),
            "delivered": _ts(ct.delivered),
            "opened": _ts(ct.opened),
            "answered": answered_ts,
        },
        "recorded_at": _ts(recorded_at),
        "answered_by": answered_by,
        "raw_event": raw_event,
        "retry_decision": flow["retry_decision"],
        "retry_after_minutes": flow["retry_after_minutes"],
        "counts_toward_cap": flow["counts_toward_cap"],
        "farmerchat_reply": flow["farmerchat_reply"],
        "needs_follow_up": needs,
        "follow_up_reasons": kept_reasons,
    }
