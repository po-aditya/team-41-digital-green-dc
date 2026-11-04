"""Schema validation tests against the supplied worked examples (read-only)."""

import json

import pytest

from farmerloop import config
from farmerloop.validate import is_valid, validate

from tests.helpers import insight_dict

SCEN = config.PARTICIPANT_PACK / "json" / "scenarios"


def _load(path):
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def test_worked_survey_examples_validate():
    for lang in ("en-IN", "hi-IN"):
        doc = _load(SCEN / "4-cow-vet-escalation" / f"survey.{lang}.json")
        assert validate("survey", doc) == []


def test_worked_handoff_validates_with_cross_file_refs():
    doc = _load(SCEN / "4-cow-vet-escalation" / "schedule_handoff.json")
    assert validate("schedule_handoff", doc) == []


def test_worked_no_survey_validates():
    doc = _load(SCEN / "6-zero-tillage-info-no-survey" / "no_survey.json")
    assert validate("no_survey", doc) == []


def test_worked_response_validates():
    doc = _load(SCEN / "4-cow-vet-escalation" / "responses" / "voice.json")
    assert validate("response", doc) == []


def test_clean_insight_validates():
    assert is_valid("insight", insight_dict())


def test_bad_survey_id_rejected():
    doc = _load(SCEN / "4-cow-vet-escalation" / "survey.en-IN.json")
    doc["survey_id"] = "S-12"
    assert any("survey_id" in e for e in validate("survey", doc))


def test_long_label_rejected():
    doc = _load(SCEN / "4-cow-vet-escalation" / "survey.en-IN.json")
    doc["items"][0]["options"][0]["label"] = "x" * 21
    assert validate("survey", doc)


def test_invalid_no_survey_reason_code_rejected():
    doc = _load(SCEN / "6-zero-tillage-info-no-survey" / "no_survey.json")
    doc["reason_code"] = "junk_insight"
    assert validate("no_survey", doc)


def test_explicit_null_relevance_score_rejected():
    doc = _load(SCEN / "4-cow-vet-escalation" / "survey.en-IN.json")
    doc["self_eval"]["relevance_score"] = None
    assert validate("survey", doc)


def test_unknown_schema_name_raises():
    with pytest.raises(KeyError):
        validate("not_a_schema", {})
