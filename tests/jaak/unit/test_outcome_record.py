"""Unit tests for outcome.py and record.py.

Validates: Requirements 1.5, 1.6, 12.1-12.3, 12.5, 12.9, 12.10, 13.1-13.7, 15.1-15.4, 15.6, 15.7.
"""
from __future__ import annotations

import copy
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from mel_agent import config, data
from mel_agent.jaak.errors import RecordInvalid
from mel_agent.jaak.logs import NullLogSink
from mel_agent.jaak.models import CallTimes, ResponseRecord, Survey
from mel_agent.jaak.outcome import (
    ItemOutcome,
    derive_status,
    follow_up_fields,
    follow_up_reasons,
    is_complete,
    success_fields,
)
from mel_agent.jaak.record import RAW_INPUT_MAX, FailureInfo, build_record

SCEN = Path(config.SCENARIOS)
IST = timezone(timedelta(hours=5, minutes=30))
UTC = timezone.utc
NOW = datetime(2027, 1, 10, 9, 0, 0, tzinfo=IST)


class Sink:
    def __init__(self):
        self.entries = []

    def write(self, entry):
        self.entries.append(entry)


class BadSink:
    def write(self, entry):
        raise RuntimeError("sink down")


def _raw(name: str, lang: str = "en-IN") -> dict:
    return json.loads((SCEN / name / f"survey.{lang}.json").read_text(encoding="utf-8"))


def _survey(name: str, lang: str = "en-IN") -> Survey:
    return Survey.model_validate(_raw(name, lang))


def _items(*specs):
    """specs: (item_id, result, value) or (item_id, result, value, attempts, raw)."""
    out = []
    for s in specs:
        out.append(
            ItemOutcome(
                s[0], s[1], s[2],
                attempts=s[3] if len(s) > 3 else (1 if s[1] == "answered" else 0),
                raw_input=s[4] if len(s) > 4 else ("raw" if s[1] == "answered" else None),
            )
        )
    return out


POTATO = "3-potato-blight-wait"  # q1 confirm, q2 select (2 follow_up), q3 scale <=1
MUSTARD = "1-mustard-aphid-spray"  # q1, q2 (not_found), q3 (same/more)


def _potato_ok(q3=5):
    return _items(("q1", "answered", "yes"), ("q2", "answered", "no_new"), ("q3", "answered", q3))


def _build(survey, outcomes, **kw):
    kw.setdefault("delivery_attempt", 1)
    kw.setdefault("recorded_at", NOW)
    kw.setdefault("log", NullLogSink())
    return build_record(survey, outcomes, **kw)


def _check_all(record: dict):
    data.validator("response").validate(record)
    model = ResponseRecord.model_validate(record)
    again = ResponseRecord.model_validate(json.loads(json.dumps(record)))
    assert again == model


# --------------------------------------------------------------------------- #
# Status table (12.1-12.3, 12.10, 13.x)
# --------------------------------------------------------------------------- #

def test_completed():
    s = _survey(POTATO)
    rec = _build(s, _potato_ok())
    assert rec["status"] == "completed"
    assert rec["complete"] is True
    assert rec["needs_follow_up"] is False and rec["follow_up_reasons"] == []


def test_partial():
    s = _survey(POTATO)
    rec = _build(s, _items(("q1", "answered", "yes"), ("q2", "skipped", None), ("q3", "not_reached", None)))
    assert rec["status"] == "partial"
    assert rec["complete"] is False
    assert rec["needs_follow_up"] is False


def test_negative_outcome_beats_partial():
    s = _survey(POTATO)
    outs = _items(("q1", "answered", "yes"), ("q2", "answered", "spreading"), ("q3", "not_reached", None))
    assert not is_complete(outs)
    rec = _build(s, outs)
    assert rec["status"] == "negative_outcome"
    assert rec["needs_follow_up"] is True
    assert rec["follow_up_reasons"] == ["crop_or_animal_damaged"]
    assert rec["complete"] is False


def test_negative_outcome_on_complete():
    rec = _build(_survey(POTATO), _potato_ok(q3=1))
    assert rec["status"] == "negative_outcome"
    assert rec["complete"] is True
    assert rec["follow_up_reasons"] == ["advice_did_not_work"]


def test_scale_at_or_below_threshold_flags_and_above_does_not():
    raw = _raw(POTATO)
    raw["items"][2]["follow_up_at_or_below"] = 2
    s = Survey.model_validate(raw)
    for v, flagged in [(1, True), (2, True), (3, False), (5, False)]:
        got = follow_up_reasons(s, _potato_ok(q3=v))
        assert (got == ["advice_did_not_work"]) is flagged, v
    assert _build(s, _potato_ok(q3=2))["status"] == "negative_outcome"
    assert _build(s, _potato_ok(q3=3))["status"] == "completed"


def test_scale_default_threshold_boundary():
    s = _survey(POTATO)  # threshold 1
    assert follow_up_reasons(s, _potato_ok(q3=1)) == ["advice_did_not_work"]
    assert follow_up_reasons(s, _potato_ok(q3=2)) == []


def test_duplicate_reason_once_first_occurrence_order():
    # mustard: q2 not_found -> could_not_get_input ; q3 same -> advice_did_not_work
    s = _survey(MUSTARD)
    outs = _items(("q1", "answered", "yes"), ("q2", "answered", "not_found"), ("q3", "answered", "same"))
    assert follow_up_reasons(s, outs) == ["could_not_get_input", "advice_did_not_work"]
    # same reason from two Items appears once
    raw = _raw(MUSTARD)
    raw["items"][1]["options"][2]["follow_up"] = "advice_did_not_work"
    s2 = Survey.model_validate(raw)
    assert follow_up_reasons(s2, outs) == ["advice_did_not_work"]
    rec = _build(s2, outs)
    assert rec["follow_up_reasons"] == ["advice_did_not_work"]


def test_reasons_follow_survey_order_not_outcome_order():
    s = _survey(MUSTARD)
    outs = _items(("q1", "answered", "yes"), ("q2", "answered", "not_found"), ("q3", "answered", "more"))
    assert follow_up_reasons(s, outs)[0] == "could_not_get_input"


def test_no_reasons_from_unaccepted_items():
    s = _survey(POTATO)
    for result in ("skipped", "invalid", "not_reached", "discarded"):
        outs = [
            ItemOutcome("q1", "answered", "yes", 1, "x"),
            ItemOutcome("q2", result, "spreading", 1, "x"),  # value must be ignored
            ItemOutcome("q3", result, 1, 1, "x"),
        ]
        assert follow_up_reasons(s, outs) == []


def test_empty_follow_up_reason_on_scale_gives_no_reason():
    s = _survey(POTATO)
    item = s.items[2].model_copy(update={"follow_up_reason": ""})
    s2 = s.model_copy(update={"items": [s.items[0], s.items[1], item]})
    assert follow_up_reasons(s2, _potato_ok(q3=1)) == []


def test_empty_option_follow_up_gives_no_reason():
    s = _survey(POTATO)
    q2 = s.items[1]
    opts = [o.model_copy(update={"follow_up": ""}) if o.value == "spreading" else o for o in q2.options]
    s2 = s.model_copy(update={"items": [s.items[0], q2.model_copy(update={"options": opts}), s.items[2]]})
    assert follow_up_reasons(s2, _potato_ok() and _items(("q1", "answered", "yes"), ("q2", "answered", "spreading"), ("q3", "answered", 5))) == []


def test_derive_status_raises_when_nothing_answered_and_no_failure():
    outs = _items(("q1", "skipped", None), ("q2", "not_reached", None), ("q3", "not_reached", None))
    with pytest.raises(ValueError):
        derive_status(outs, [])


def test_failure_status_wins_and_clears_follow_up():
    outs = _items(("q1", "answered", "yes"), ("q2", "answered", "spreading"), ("q3", "not_reached", None))
    assert derive_status(outs, ["crop_or_animal_damaged"], failure="expired") == "expired"
    assert follow_up_fields("expired", ["crop_or_animal_damaged"], failure=True) == (False, [])
    assert follow_up_fields("expired", ["x"]) == (False, [])
    assert follow_up_fields("negative_outcome", ["x"]) == (True, ["x"])
    assert follow_up_fields("completed", []) == (False, [])


def test_success_fields_values():
    for st in ("completed", "partial", "negative_outcome"):
        assert success_fields(st) == {
            "retry_decision": "none",
            "retry_after_minutes": None,
            "counts_toward_cap": True,
            "farmerchat_reply": None,
        }
    with pytest.raises(ValueError):
        success_fields("expired")


def test_is_complete_flag():
    assert is_complete(_potato_ok())
    assert not is_complete(_items(("q1", "answered", "yes"), ("q2", "invalid", None)))
    assert not is_complete([])


# --------------------------------------------------------------------------- #
# Record building
# --------------------------------------------------------------------------- #

def test_response_key_deterministic_and_short():
    s = _survey(POTATO)
    a = _build(s, _potato_ok(), delivery_attempt=2)
    b = _build(s, _potato_ok(), delivery_attempt=2)
    assert a["response_key"] == b["response_key"] == f"rk-{s.survey_id}-voice-2"
    assert 1 <= len(a["response_key"]) <= 64
    assert _build(s, _potato_ok(), delivery_attempt=3)["response_key"] != a["response_key"]


def test_timestamps_in_ist_for_non_ist_clock():
    s = _survey(POTATO)
    utc_now = datetime(2027, 1, 10, 3, 30, 15, 999, tzinfo=UTC)
    ct = CallTimes(sent=datetime(2027, 1, 10, 3, 0, tzinfo=UTC), opened=datetime(2027, 1, 10, 3, 20, tzinfo=UTC))
    rec = _build(s, _potato_ok(), recorded_at=utc_now, call_times=ct)
    assert rec["recorded_at"] == "2027-01-10T09:00:15+05:30"
    assert rec["timestamps"]["answered"] == "2027-01-10T09:00:15+05:30"
    assert rec["timestamps"]["sent"] == "2027-01-10T08:30:00+05:30"
    assert rec["timestamps"]["opened"] == "2027-01-10T08:50:00+05:30"
    assert rec["timestamps"]["delivered"] is None
    for v in (rec["recorded_at"], rec["timestamps"]["sent"], rec["timestamps"]["opened"]):
        assert v.endswith("+05:30")


def test_answered_at_override_used():
    s = _survey(POTATO)
    ans = datetime(2027, 1, 10, 3, 31, tzinfo=UTC)
    rec = _build(s, _potato_ok(), answered_at=ans)
    assert rec["timestamps"]["answered"] == "2027-01-10T09:01:00+05:30"


def test_fixed_clock_byte_identical():
    s = _survey(POTATO)
    a = json.dumps(_build(s, _potato_ok()), sort_keys=False)
    b = json.dumps(_build(s, _potato_ok()), sort_keys=False)
    assert a == b


def test_answers_only_for_answered_and_items_in_survey_order():
    s = _survey(POTATO)
    outs = [
        ItemOutcome("q1", "answered", "yes", 1, "yes please"),
        ItemOutcome("q2", "invalid", None, 3, "garbage"),
        ItemOutcome("q3", "not_reached", None, 0, None),
    ]
    rec = _build(s, outs)
    assert rec["answers"] == {"q1": "yes"}
    assert [i["item_id"] for i in rec["items"]] == ["q1", "q2", "q3"]
    assert [i["result"] for i in rec["items"]] == ["answered", "invalid", "not_reached"]
    assert [i["item_type"] for i in rec["items"]] == [it.type for it in s.items]
    assert [i["input_kind"] for i in rec["items"]] == ["speech", None, None]
    assert rec["items"][1]["raw_input"] is None and rec["items"][1]["value"] is None
    assert rec["items"][1]["attempts"] == 3
    _check_all(rec)


def test_skipped_item_recorded():
    s = _survey(POTATO)
    rec = _build(s, _items(("q1", "answered", "yes"), ("q2", "skipped", None), ("q3", "answered", 4)))
    assert rec["answers"] == {"q1": "yes", "q3": 4}
    assert rec["items"][1]["result"] == "skipped"
    assert rec["status"] == "partial"


def test_raw_input_truncated():
    s = _survey(POTATO)
    long = "a" * 1000
    outs = [
        ItemOutcome("q1", "answered", "yes", 1, long),
        ItemOutcome("q2", "answered", "no_new", 1, "b" * RAW_INPUT_MAX),
        ItemOutcome("q3", "answered", 5, 1, None),
    ]
    rec = _build(s, outs)
    assert len(rec["items"][0]["raw_input"]) == 256
    assert len(rec["items"][1]["raw_input"]) == 256
    assert rec["items"][2]["raw_input"] is None


def test_answered_by_rules():
    s = _survey(POTATO)
    rec = _build(s, _potato_ok())
    assert rec["answered_by"] == s.farmer_id
    none_answered = _items(("q1", "skipped", None), ("q2", "not_reached", None), ("q3", "not_reached", None))
    fail = FailureInfo("window_expired", "expired", "give_up", None, True)
    rec2 = _build(s, none_answered, failure=fail)
    assert rec2["answered_by"] is None
    assert rec2["timestamps"]["answered"] is None
    fail_ov = FailureInfo("identity_mismatch", "identity_mismatch", "give_up", None, True, answered_by="F-999999")
    rec3 = _build(s, none_answered, failure=fail_ov)
    assert rec3["answered_by"] == "F-999999"
    # failure after an answer: farmer_id
    part = _items(("q1", "answered", "yes"), ("q2", "not_reached", None), ("q3", "not_reached", None))
    assert _build(s, part, failure=fail)["answered_by"] == s.farmer_id


def test_window_expired_failure_builds_valid_record():
    s = _survey(POTATO)
    d = data.outcome_codes()["failures"]["window_expired"] if hasattr(data, "outcome_codes") else None
    if d is None:
        d = json.loads((Path(config.SCENARIOS).parent / "rules" / "outcome_codes.json").read_text())["failures"]["window_expired"]
    fail = FailureInfo(
        "window_expired", d["status"], d["retry_decision"], d["retry_after_minutes"], d["counts_toward_cap"],
        raw_event="r" * 400,
    )
    outs = _items(("q1", "answered", "yes"), ("q2", "answered", "spreading"), ("q3", "not_reached", None))
    rec = _build(s, outs, failure=fail)
    assert rec["status"] == "expired"
    assert rec["failure_code"] == "window_expired"
    assert rec["counts_toward_cap"] is d["counts_toward_cap"]
    assert rec["retry_decision"] == d["retry_decision"]
    assert rec["needs_follow_up"] is False and rec["follow_up_reasons"] == []
    assert rec["farmerchat_reply"] is None
    assert len(rec["raw_event"]) == 256
    _check_all(rec)


def test_failure_with_nothing_answered_valid():
    s = _survey(POTATO)
    fail = FailureInfo("window_expired", "expired", "give_up", None, True)
    rec = _build(s, _items(("q1", "not_reached", None), ("q2", "not_reached", None), ("q3", "not_reached", None)), failure=fail)
    assert rec["status"] == "expired" and rec["answers"] == {} and rec["complete"] is False
    _check_all(rec)


@pytest.mark.parametrize("name", sorted(p.name for p in SCEN.iterdir() if (p / "survey.en-IN.json").exists()))
@pytest.mark.parametrize("lang", ["en-IN", "hi-IN"])
def test_scenario_records_validate_and_round_trip(name, lang):
    s = _survey(name, lang)
    outs = []
    for it in s.items:
        v = it.scale_min if it.type == "survey-scale" else it.options[0].value
        outs.append(ItemOutcome(it.item_id, "answered", v, 1, "x"))
    rec = _build(s, outs)
    _check_all(rec)
    assert rec["language"] == lang
    assert rec["channel"] == "voice"
    assert rec["source_insight_ids"] == list(s.source_insight_ids)


def test_record_has_no_personal_fields():
    s = _survey(POTATO)
    rec = _build(s, _potato_ok())
    text = json.dumps(rec)
    for k in ("farmer_name", "state", "district"):
        assert k not in rec
        assert f'"{k}"' not in text


# --------------------------------------------------------------------------- #
# Fault injection and logging (1.6)
# --------------------------------------------------------------------------- #

def test_naive_datetime_raises_record_invalid():
    s = _survey(POTATO)
    sink = Sink()
    with pytest.raises(RecordInvalid):
        _build(s, _potato_ok(), recorded_at=datetime(2027, 1, 10, 9, 0, 0), log=sink)
    assert len(sink.entries) == 1


def test_naive_answered_at_raises_record_invalid():
    s = _survey(POTATO)
    with pytest.raises(RecordInvalid):
        _build(s, _potato_ok(), answered_at=datetime(2027, 1, 10, 9, 0, 0))


def test_mismatched_item_ids_raise_record_invalid():
    s = _survey(POTATO)
    bad_sets = [
        _items(("q1", "answered", "yes"), ("q2", "answered", "no_new"), ("zz", "answered", 3)),
        _items(("q1", "answered", "yes"), ("q2", "answered", "no_new")),
        _items(("q2", "answered", "no_new"), ("q1", "answered", "yes"), ("q3", "answered", 3)),
        _items(("q1", "answered", "yes"), ("q1", "answered", "yes"), ("q3", "answered", 3)),
    ]
    for outs in bad_sets:
        sink = Sink()
        with pytest.raises(RecordInvalid):
            _build(s, outs, log=sink)
        assert len(sink.entries) == 1


def test_bad_record_raises_and_returns_nothing():
    s = _survey(POTATO)
    # unknown failure code -> schema/model rejects the built record
    outs = _items(("q1", "not_reached", None), ("q2", "not_reached", None), ("q3", "not_reached", None))
    bad = FailureInfo("not_a_code", "expired", "give_up", None, True)
    result = None
    sink = Sink()
    with pytest.raises(RecordInvalid) as ei:
        result = _build(s, outs, log=sink, failure=bad)
    assert result is None
    assert ei.value.failures
    assert ei.value.logging_failed is False
    assert len(sink.entries) == 1
    e = sink.entries[0]
    assert e["boundary"] == "response_record_output"
    assert "no_new" not in json.dumps(e)


def test_bad_failure_info_raises():
    s = _survey(POTATO)
    fail = FailureInfo("not_a_code", "expired", "give_up", None, True)
    outs = _items(("q1", "not_reached", None), ("q2", "not_reached", None), ("q3", "not_reached", None))
    with pytest.raises(RecordInvalid):
        _build(s, outs, failure=fail)


def test_nothing_answered_no_failure_raises_record_invalid():
    s = _survey(POTATO)
    outs = _items(("q1", "skipped", None), ("q2", "not_reached", None), ("q3", "not_reached", None))
    with pytest.raises(RecordInvalid):
        _build(s, outs)


def test_sink_receives_no_entries_on_success():
    sink = Sink()
    _build(_survey(POTATO), _potato_ok(), log=sink)
    assert sink.entries == []


def test_failing_sink_sets_logging_failed():
    s = _survey(POTATO)
    outs = _items(("q1", "not_reached", None), ("q2", "not_reached", None), ("q3", "not_reached", None))
    bad = FailureInfo("not_a_code", "expired", "give_up", None, True)
    with pytest.raises(RecordInvalid) as ei:
        _build(s, outs, log=BadSink(), failure=bad)
    assert ei.value.logging_failed is True


def test_failing_sink_not_called_on_success():
    # a broken sink must not matter when the record is valid
    rec = _build(_survey(POTATO), _potato_ok(), log=BadSink())
    assert rec["status"] == "completed"
