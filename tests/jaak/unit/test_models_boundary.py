"""Unit tests for models.py and boundary.py (Req 1.1, 1.2, 1.3, 1.7, 3.4, 15.5, 18.8).

Conforming examples come from the participant pack. Violating examples are built
by mutating conforming ones. JSON Schema and Pydantic must agree on every case.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from mel_agent import config, data
from mel_agent.jaak import boundary, models
from mel_agent.jaak.errors import InputRejected, InvalidRequest

SCEN = Path(config.SCENARIOS)
MODEL_FOR = {
    "survey": models.Survey,
    "response": models.ResponseRecord,
    "schedule_handoff": models.ScheduleHandoff,
    "no_survey": models.NoSurvey,
    "insight": models.Insight,
    "bottom_sheet": models.BottomSheet,
}


def _load(p: Path):
    return json.loads(p.read_text(encoding="utf-8"))


def _conforming() -> list[tuple[str, str, dict]]:
    out: list[tuple[str, str, dict]] = []
    for d in sorted(SCEN.iterdir()):
        for p in sorted(d.glob("survey.*.json")):
            out.append(("survey", f"{d.name}/{p.name}", _load(p)))
        if (d / "schedule_handoff.json").exists():
            out.append(("schedule_handoff", f"{d.name}/handoff", _load(d / "schedule_handoff.json")))
        if (d / "no_survey.json").exists():
            out.append(("no_survey", f"{d.name}/no_survey", _load(d / "no_survey.json")))
        out.append(("insight", f"{d.name}/insight", _load(d / "insight.json")))
        for p in sorted((d / "responses").glob("*.json")) if (d / "responses").exists() else []:
            out.append(("response", f"{d.name}/responses/{p.name}", _load(p)))
        for p in sorted((d / "render").glob("*/*.json")) if (d / "render").exists() else []:
            doc = _load(p)
            if "presentation" in doc and "sheet" in doc:
                part = {"presentation": doc["presentation"], "sheet": doc["sheet"]}
                out.append(("bottom_sheet", f"{d.name}/render/{p.parent.name}/{p.name}", part))
    first = (config.PACK / "data" / "insights.jsonl").read_text(encoding="utf-8").splitlines()[0]
    out.append(("insight", "insights.jsonl/0", json.loads(first)))
    return out


CONFORMING = _conforming()
IDS = [f"{k}:{n}" for k, n, _ in CONFORMING]


def _schema_ok(kind, doc) -> bool:
    return not list(data.validator(kind).iter_errors(doc))


def _model_ok(kind, doc) -> bool:
    try:
        MODEL_FOR[kind].model_validate(doc)
        return True
    except ValidationError:
        return False


def test_all_six_schemas_are_covered():
    assert {k for k, _, _ in CONFORMING} == set(MODEL_FOR)


@pytest.mark.parametrize("kind,name,doc", CONFORMING, ids=IDS)
def test_conforming_example_accepted_by_both(kind, name, doc):
    assert _schema_ok(kind, doc)
    assert _model_ok(kind, doc)


def _wrong_type(v):
    return 12345 if isinstance(v, str) else "x"


def _mutations(doc: dict):
    """Yield (label, mutated) for missing key, extra key, wrong type at the root."""
    for k in doc:
        m = copy.deepcopy(doc)
        del m[k]
        yield f"missing:{k}", m
        m = copy.deepcopy(doc)
        m[k] = _wrong_type(m[k])
        yield f"wrongtype:{k}", m
    m = copy.deepcopy(doc)
    m["unexpected_key"] = 1
    yield "extra", m


@pytest.mark.parametrize("kind,name,doc", CONFORMING, ids=IDS)
def test_mutated_examples_get_same_verdict_from_both(kind, name, doc):
    rejected = 0
    for label, m in _mutations(doc):
        s_ok, p_ok = _schema_ok(kind, m), _model_ok(kind, m)
        assert s_ok == p_ok, f"{label}: schema={s_ok} pydantic={p_ok}"
        rejected += not s_ok
    assert rejected >= 1


def _first(kind, pred=lambda d: True):
    return next(copy.deepcopy(d) for k, _, d in CONFORMING if k == kind and pred(d))


def _both_reject(kind, doc):
    assert not _schema_ok(kind, doc)
    assert not _model_ok(kind, doc)


def test_survey_bad_pattern_and_range_rejected():
    s = _first("survey")
    s["survey_id"] = "X-1"
    _both_reject("survey", s)
    s = _first("survey")
    s["items"][0]["prompt"] = ""
    _both_reject("survey", s)
    s = _first("survey")
    s["items"] = s["items"] * 4  # more than 3
    _both_reject("survey", s)
    s = _first("survey")
    s["farmer_id"] = "F" * 65
    _both_reject("survey", s)


def test_response_out_of_range_and_bad_pattern_rejected():
    for field, bad in [("delivery_attempt", 6), ("delivery_attempt", 0), ("survey_id", "bad"),
                       ("recorded_at", "2026-01-01T00:00:00Z"), ("status", "nope")]:
        r = _first("response")
        r[field] = bad
        _both_reject("response", r)


def test_handoff_bad_values_rejected():
    h = _first("schedule_handoff")
    h["priority"] = "urgent"
    _both_reject("schedule_handoff", h)
    h = _first("schedule_handoff")
    h["send_hours"]["from"] = "25:00"
    _both_reject("schedule_handoff", h)


def test_no_survey_and_bottom_sheet_bad_values_rejected():
    n = _first("no_survey")
    n["reason_code"] = "other"
    _both_reject("no_survey", n)
    b = _first("bottom_sheet")
    b["presentation"]["can_skip"] = False
    _both_reject("bottom_sheet", b)


def test_insight_bad_values_rejected():
    i = _first("insight")
    i["severity"] = "extreme"
    _both_reject("insight", i)


# --------------------------------------------------------------------------- #
# Boundary behaviour
# --------------------------------------------------------------------------- #
class Rec:
    def __init__(self):
        self.entries: list[dict] = []

    def write(self, entry: dict) -> None:
        self.entries.append(entry)


SENTINEL = "ZQXSECRETTEXT"


def _en_survey():
    return _first("survey", lambda d: d["language"] == "en-IN")


def _farmer(survey=None, **kw):
    f = {"farmer_id": (survey or _en_survey())["farmer_id"], "language": "en-IN",
         "state": "Bihar", "district": "Patna"}
    f.update(kw)
    return f


def test_survey_accepted_and_no_log():
    sink = Rec()
    r = boundary.validate_survey(_en_survey(), sink)
    assert r.ok and isinstance(r.model, models.Survey)
    assert sink.entries == []


def test_survey_unsupported_language_rejected():
    for lang in ("ta-IN", "en-US", "en-in", "fr-FR"):
        s = _en_survey()
        s["language"] = lang
        sink = Rec()
        r = boundary.validate_survey(s, sink)
        assert not r.ok, lang
        assert len(sink.entries) == 1


def test_survey_schema_failure_logs_once():
    s = _en_survey()
    del s["rationale"]
    sink = Rec()
    r = boundary.validate_survey(s, sink)
    assert not r.ok
    assert ("/", "required") in r.failures
    assert len(sink.entries) == 1 and sink.entries[0]["boundary"] == "survey_input"


def test_farmer_id_65_chars_rejected_64_accepted():
    sink = Rec()
    assert not boundary.validate_farmer_record(_farmer(farmer_id="F" * 65), sink).ok
    assert len(sink.entries) == 1
    assert boundary.validate_farmer_record(_farmer(farmer_id="F" * 64), Rec()).ok


@pytest.mark.parametrize("fid", ["", "   ", "\t\n"])
def test_blank_farmer_id_rejected(fid):
    sink = Rec()
    assert not boundary.validate_farmer_record(_farmer(farmer_id=fid), sink).ok
    assert len(sink.entries) == 1


@pytest.mark.parametrize("lang", ["en-in", "EN-IN", "hi-in", "ta-IN", "en-US", "", "en_IN", None, 5])
def test_farmer_language_rejected(lang):
    sink = Rec()
    assert not boundary.validate_farmer_record(_farmer(language=lang), sink).ok
    assert len(sink.entries) == 1


@pytest.mark.parametrize("lang", ["hi-IN", "en-IN"])
def test_farmer_supported_language_accepted_and_extra_columns_dropped(lang):
    r = boundary.validate_farmer_record(_farmer(language=lang), Rec())
    assert r.ok
    assert not hasattr(r.model, "state") and not hasattr(r.model, "district")


def test_farmer_record_non_dict_rejected():
    sink = Rec()
    assert not boundary.validate_farmer_record("F-1", sink).ok
    assert len(sink.entries) == 1


def test_pair_match_and_mismatch():
    s = boundary.validate_survey(_en_survey(), Rec()).model
    f = boundary.validate_farmer_record(_farmer(), Rec()).model
    assert boundary.validate_pair(s, f, Rec()).ok
    f2 = boundary.validate_farmer_record(_farmer(farmer_id="F-999999"), Rec()).model
    sink = Rec()
    r = boundary.validate_pair(s, f2, sink)
    assert not r.ok and len(sink.entries) == 1
    assert sink.entries[0]["boundary"] == "survey_farmer_pair"


def test_language_mismatch_warns_once_survey_wins():
    s = boundary.validate_survey(_en_survey(), Rec()).model
    f = boundary.validate_farmer_record(_farmer(language="hi-IN"), Rec()).model
    sink = Rec()
    assert boundary.detect_language_mismatch(s, f, sink) is True
    assert len(sink.entries) == 1 and sink.entries[0]["level"] == "warning"
    same = boundary.validate_farmer_record(_farmer(language="en-IN"), Rec()).model
    sink = Rec()
    assert boundary.detect_language_mismatch(s, same, sink) is False
    assert sink.entries == []


def test_validate_inputs_order_and_raising():
    sink = Rec()
    bad_s = _en_survey()
    bad_s["survey_id"] = "bad"
    with pytest.raises(InputRejected):
        boundary.validate_inputs(bad_s, _farmer(farmer_id="F" * 65), sink)
    assert len(sink.entries) == 1 and sink.entries[0]["boundary"] == "survey_input"

    sink = Rec()
    with pytest.raises(InputRejected):
        boundary.validate_inputs(_en_survey(), _farmer(farmer_id="F-999999"), sink)
    assert len(sink.entries) == 1 and sink.entries[0]["boundary"] == "survey_farmer_pair"

    sink = Rec()
    r = boundary.validate_inputs(_en_survey(), _farmer(), sink)
    assert r.ok and sink.entries == []


@pytest.mark.parametrize("v", [1, 2, 3, 4, 5])
def test_delivery_attempt_valid(v):
    sink = Rec()
    r = boundary.validate_delivery_attempt(v, sink)
    assert r.ok and r.model == v and sink.entries == []
    assert boundary.require_delivery_attempt(v, sink) == v


@pytest.mark.parametrize("v", [0, 6, True, False, 2.0, "1", None, -1])
def test_delivery_attempt_invalid(v):
    sink = Rec()
    assert not boundary.validate_delivery_attempt(v, sink).ok
    assert len(sink.entries) == 1
    assert sink.entries[0]["boundary"] == "call_parameters"
    with pytest.raises(InvalidRequest):
        boundary.require_delivery_attempt(v, Rec())


def test_answer_boundaries():
    for ok in ("", "   ", "yes", "x" * 2000, "हाँ"):
        sink = Rec()
        assert boundary.validate_transcribed_answer(ok, sink).ok
        assert sink.entries == []
    for bad in ("x" * 2001, 5, None, b"yes", ["yes"]):
        sink = Rec()
        assert not boundary.validate_transcribed_answer(bad, sink).ok
        assert len(sink.entries) == 1
        with pytest.raises(InvalidRequest):
            boundary.require_transcribed_answer(bad, Rec())


# --------------------------------------------------------------------------- #
# Logs hold no free text from the input
# --------------------------------------------------------------------------- #
def _dump(sink: Rec) -> str:
    return json.dumps(sink.entries, ensure_ascii=False)


def test_logs_contain_no_input_text():
    sink = Rec()
    s = _en_survey()
    s["rationale"] = ""
    s["items"][0]["prompt"] = SENTINEL
    s["extra"] = SENTINEL
    s["farmer_id"] = SENTINEL * 8
    boundary.validate_survey(s, sink)
    boundary.validate_farmer_record(_farmer(farmer_id=SENTINEL * 8, language=SENTINEL), sink)
    boundary.validate_farmer_record(_farmer(farmer_id=" " * 3, language="en-in"), sink)
    boundary.validate_transcribed_answer(SENTINEL * 400, sink)
    boundary.validate_transcribed_answer({"k": SENTINEL}, sink)
    boundary.validate_delivery_attempt(SENTINEL, sink)
    assert len(sink.entries) == 6
    assert SENTINEL not in _dump(sink)
    assert sink.entries[3]["length"] == len(SENTINEL) * 400


def test_failing_sink_does_not_change_rejection():
    class Boom:
        def write(self, entry):
            raise RuntimeError("down")

    r = boundary.validate_delivery_attempt(0, Boom())
    assert not r.ok and r.logging_failed
