"""Boundary validators for the JAAK core engine (Req 1, 3.4, 15.5, 18.8, 20).

Every validator returns a ``BoundaryResult(ok, model, failures)``. Failures are
``(json_path, keyword)`` pairs. Reasons are schema keywords only; library
messages and offending values are never copied into results or log entries.
Each rejection writes exactly one log entry through the ``LogSink``. If the
sink raises, the result carries ``logging_failed=True`` and the rejection
stands (Req 19.6). The ``raise_*`` helpers turn a rejected result into the
matching error from ``errors.py`` so the engine can reject with state unchanged.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

from pydantic import ValidationError

from .. import data
from .errors import InputRejected, InvalidRequest
from .logs import LogSink
from .models import SUPPORTED_LANGUAGES, FarmerRecord, Survey

_LOG = logging.getLogger("mel_agent.jaak")

MAX_ANSWER_CHARS = 2000
MIN_ATTEMPT, MAX_ATTEMPT = 1, 5

Failure = tuple[str, str]


@dataclass(frozen=True)
class BoundaryResult:
    ok: bool
    model: Any = None
    failures: tuple[Failure, ...] = ()
    logging_failed: bool = False


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _pointer(parts) -> str:
    return "/" + "/".join(str(p) for p in parts)


_PYDANTIC_KEYWORDS = {
    "missing": "required",
    "extra_forbidden": "additionalProperties",
    "string_too_short": "minLength",
    "string_too_long": "maxLength",
    "too_short": "minItems",
    "too_long": "maxItems",
    "greater_than_equal": "minimum",
    "less_than_equal": "maximum",
    "literal_error": "enum",
    "union_tag_invalid": "enum",
}


def _pydantic_failures(exc: ValidationError) -> list[Failure]:
    out: list[Failure] = []
    for err in exc.errors(include_url=False, include_context=True, include_input=False):
        kind = err.get("type", "")
        if kind in _PYDANTIC_KEYWORDS:
            keyword = _PYDANTIC_KEYWORDS[kind]
        elif kind == "value_error":
            # Our own validators raise fixed keywords (e.g. "pattern", "blank").
            raw = str(err.get("ctx", {}).get("error", ""))
            keyword = raw if raw.isidentifier() else "value_error"
        elif kind.endswith("_type") or kind.endswith("_parsing") or kind == "model_type":
            keyword = "type"
        else:
            keyword = "type"
        out.append((_pointer(err.get("loc", ())), keyword))
    return out


def _dedupe(failures) -> tuple[Failure, ...]:
    return tuple(sorted(set(failures)))


def _safe_id(doc: Any, key: str, failures) -> Optional[str]:
    """Return an id for logging only when it is a clean string that passed validation."""
    if not isinstance(doc, dict) or not isinstance(doc.get(key), str):
        return None
    if any(p == f"/{key}" or p.startswith(f"/{key}/") for p, _ in failures):
        return None
    value = doc[key]
    return value if 1 <= len(value) <= 64 else None


def _emit(sink: LogSink, entry: dict) -> bool:
    """Write one entry. Returns True if the sink failed (fallback goes to logging)."""
    try:
        sink.write(entry)
        return False
    except Exception:  # noqa: BLE001 - the rejection must stand whatever the sink does
        try:
            _LOG.error("log sink failed: %s", entry)
        except Exception:  # noqa: BLE001
            pass
        return True


def _reject(
    sink: LogSink,
    boundary: str,
    failures,
    *,
    level: str = "reject",
    survey_id: Optional[str] = None,
    farmer_id: Optional[str] = None,
    note: Optional[str] = None,
    extra: Optional[dict] = None,
) -> BoundaryResult:
    failures = _dedupe(failures)
    entry: dict = {"event": "rejection", "level": level, "boundary": boundary}
    if survey_id is not None:
        entry["survey_id"] = survey_id
    if farmer_id is not None:
        entry["farmer_id"] = farmer_id
    entry["failures"] = [{"path": p, "reason": r} for p, r in failures]
    if note:
        entry["note"] = note
    if extra:
        entry.update(extra)
    failed = _emit(sink, entry)
    return BoundaryResult(False, None, failures, failed)


# --------------------------------------------------------------------------- #
# Survey (Req 1.2, 1.4, 3.4)
# --------------------------------------------------------------------------- #
def validate_survey(doc: Any, sink: LogSink) -> BoundaryResult:
    schema_failures = [
        (_pointer(e.absolute_path) if e.absolute_path else "/", str(e.validator))
        for e in data.validator("survey").iter_errors(doc)
    ]
    if schema_failures:
        return _reject(
            sink, "survey_input", schema_failures,
            survey_id=_safe_id(doc, "survey_id", schema_failures),
            farmer_id=_safe_id(doc, "farmer_id", schema_failures),
        )
    try:
        model = Survey.model_validate(doc)
    except ValidationError as exc:
        fails = _pydantic_failures(exc) or [("/", "type")]
        return _reject(
            sink, "survey_input", fails,
            survey_id=_safe_id(doc, "survey_id", fails),
            farmer_id=_safe_id(doc, "farmer_id", fails),
        )
    if model.language not in SUPPORTED_LANGUAGES:  # exact, case-sensitive
        return _reject(
            sink, "survey_input", [("/language", "enum")],
            survey_id=model.survey_id, farmer_id=model.farmer_id,
        )
    return BoundaryResult(True, model, ())


# --------------------------------------------------------------------------- #
# Farmer_Record (Req 1.3)
# --------------------------------------------------------------------------- #
def validate_farmer_record(doc: Any, sink: LogSink) -> BoundaryResult:
    if not isinstance(doc, dict):
        return _reject(sink, "farmer_record_input", [("/", "type")])
    try:
        model = FarmerRecord.model_validate(doc)
    except ValidationError as exc:
        fails = _pydantic_failures(exc) or [("/", "type")]
        return _reject(
            sink, "farmer_record_input", fails,
            farmer_id=_safe_id(doc, "farmer_id", fails),
        )
    return BoundaryResult(True, model, ())


# --------------------------------------------------------------------------- #
# Pair (Req 1.7) and language mismatch (Req 3.5)
# --------------------------------------------------------------------------- #
def validate_pair(survey: Survey, farmer: FarmerRecord, sink: LogSink) -> BoundaryResult:
    if survey.farmer_id != farmer.farmer_id:
        return _reject(
            sink, "survey_farmer_pair", [("/farmer_id", "const")],
            survey_id=survey.survey_id,
            farmer_id=survey.farmer_id,
            extra={"farmer_record_farmer_id": farmer.farmer_id},
        )
    return BoundaryResult(True, (survey, farmer), ())


def detect_language_mismatch(survey: Survey, farmer: FarmerRecord, sink: LogSink) -> bool:
    """True when the supported languages differ. Writes one warning; Survey language wins."""
    if survey.language == farmer.language:
        return False
    _emit(sink, {
        "event": "rejection",
        "level": "warning",
        "boundary": "survey_farmer_pair",
        "survey_id": survey.survey_id,
        "farmer_id": survey.farmer_id,
        "failures": [],
        "note": "language_mismatch",
        "survey_language": survey.language,
        "farmer_language": farmer.language,
    })
    return True


def validate_inputs(survey_doc: Any, farmer_doc: Any, sink: LogSink) -> BoundaryResult:
    """Survey, then Farmer_Record, then pair. The first failing boundary wins (Req 1.4)."""
    s = validate_survey(survey_doc, sink)
    if not s.ok:
        raise_input_rejected("survey_input", s)
    f = validate_farmer_record(farmer_doc, sink)
    if not f.ok:
        raise_input_rejected("farmer_record_input", f)
    p = validate_pair(s.model, f.model, sink)
    if not p.ok:
        raise_input_rejected("survey_farmer_pair", p)
    return BoundaryResult(True, (s.model, f.model), ())


# --------------------------------------------------------------------------- #
# delivery_attempt (Req 18.8) and Transcribed_Answer (Req 20.1, 20.7)
# --------------------------------------------------------------------------- #
def validate_delivery_attempt(value: Any, sink: LogSink) -> BoundaryResult:
    if isinstance(value, bool) or not isinstance(value, int):
        return _reject(sink, "call_parameters", [("/delivery_attempt", "type")])
    if value < MIN_ATTEMPT:
        return _reject(sink, "call_parameters", [("/delivery_attempt", "minimum")])
    if value > MAX_ATTEMPT:
        return _reject(sink, "call_parameters", [("/delivery_attempt", "maximum")])
    return BoundaryResult(True, value, ())


def validate_transcribed_answer(value: Any, sink: LogSink) -> BoundaryResult:
    """Guard only: str, at most 2,000 code points. Logs length and reason, never text."""
    if not isinstance(value, str):
        return _reject(sink, "transcribed_answer_input", [("/answer", "type")])
    if len(value) > MAX_ANSWER_CHARS:
        return _reject(
            sink, "transcribed_answer_input", [("/answer", "maxLength")],
            extra={"length": len(value)},
        )
    return BoundaryResult(True, value, ())


# --------------------------------------------------------------------------- #
# Raising helpers
# --------------------------------------------------------------------------- #
def raise_input_rejected(boundary: str, result: BoundaryResult) -> None:
    raise InputRejected(boundary, result.failures, logging_failed=result.logging_failed)


def raise_invalid_request(boundary: str, result: BoundaryResult) -> None:
    raise InvalidRequest(
        boundary=boundary, failures=result.failures, logging_failed=result.logging_failed
    )


def require_delivery_attempt(value: Any, sink: LogSink) -> int:
    r = validate_delivery_attempt(value, sink)
    if not r.ok:
        raise_invalid_request("call_parameters", r)
    return r.model


def require_transcribed_answer(value: Any, sink: LogSink) -> str:
    r = validate_transcribed_answer(value, sink)
    if not r.ok:
        raise_invalid_request("transcribed_answer_input", r)
    return r.model
