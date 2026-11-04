"""Self-check and quality gate: nothing that fails a check gets a scheduler hand-off."""
import copy

import pytest

from conftest import GOOD_EN, GOOD_HI, GOOD_VERDICT, make_survey
from mel_agent import checker, config, data, pipeline, rules


def test_threshold_is_0_8():
    assert config.MIN_RELEVANCE == 0.8


# ---------- malformed surveys ----------

def test_missing_send_window_fails_deterministic(insight):
    s = make_survey(insight, GOOD_EN["items"])
    del s["send_window"]
    problems = checker.deterministic(s)
    assert any("send_window" in p for p in problems)


def test_long_label_fails_deterministic(insight):
    items = copy.deepcopy(GOOD_EN["items"])
    items[0]["options"][0]["label"] = "Yes, I sprayed all of it"  # 24 characters
    problems = checker.deterministic(make_survey(insight, items))
    assert any("max 20" in p for p in problems)


def test_phone_number_question_fails_deterministic(insight):
    items = copy.deepcopy(GOOD_EN["items"])
    items[1]["prompt"] = "What is your phone number?"
    problems = checker.deterministic(make_survey(insight, items))
    assert any("personal information" in p for p in problems)


def test_well_formed_survey_passes_deterministic(insight):
    assert checker.deterministic(make_survey(insight, GOOD_EN["items"])) == []
    assert checker.deterministic(make_survey(insight, GOOD_HI["items"], language="hi-IN")) == []


def test_malformed_draft_is_rejected_without_handoff(insight, fake_llm):
    draft = copy.deepcopy(GOOD_EN)
    draft["items"][0]["options"][0]["label"] = "Yes, I sprayed all of it"
    draft["items"][1]["prompt"] = "What is your phone number?"
    fake_llm.draft = draft
    r = pipeline.process(insight, "en-IN")
    assert r["status"] == "rejected"
    assert r["handoff"] is None
    assert r["check"]["passed"] is False
    assert "review_survey" not in fake_llm.calls  # the judge is skipped when code checks fail


def test_no_send_window_is_rejected_without_handoff(insight, fake_llm, monkeypatch):
    real = rules.decide

    def no_window(ins, policy=rules.DEFAULT_POLICY):
        d = real(ins, policy)
        d.send_window = None
        return d
    monkeypatch.setattr(pipeline.rules, "decide", no_window)
    r = pipeline.process(insight, "en-IN")
    assert r["status"] == "rejected"
    assert r["handoff"] is None
    assert any("send_window" in p for p in r["check"]["deterministic"])


# ---------- relevance threshold ----------

@pytest.mark.parametrize("score,status", [(0.79, "rejected"), (0.8, "scheduled"), (0.85, "scheduled")])
def test_relevance_threshold(insight, fake_llm, score, status):
    fake_llm.verdict["relevance_score"] = score
    r = pipeline.process(insight, "en-IN")
    assert r["status"] == status
    assert (r["handoff"] is not None) == (status == "scheduled")
    if status == "scheduled":
        assert data.schema_errors("schedule_handoff", r["handoff"]) == []
    else:
        assert any("below 0.8" in x for x in r["check"]["reasons"])


@pytest.mark.parametrize("bad", [float("nan"), None, "high"])
def test_unusable_relevance_score_is_rejected(insight, fake_llm, bad):
    fake_llm.verdict["relevance_score"] = bad
    r = pipeline.process(insight, "en-IN")
    assert r["status"] == "rejected"
    assert r["handoff"] is None


def test_passes_rule_directly():
    v = dict(GOOD_VERDICT)
    assert checker.passes([], {**v, "relevance_score": 0.79})[0] is False
    assert checker.passes([], {**v, "relevance_score": 0.8})[0] is True


# ---------- safety flags from the judge ----------

@pytest.mark.parametrize("flag,message", [("gives_new_advice", "gives new advice"),
                                          ("asks_personal_info", "asks for personal information")])
def test_safety_flags_reject(insight, fake_llm, flag, message):
    fake_llm.verdict[flag] = True
    r = pipeline.process(insight, "en-IN")
    assert r["status"] == "rejected"
    assert r["handoff"] is None
    assert message in r["check"]["reasons"]


# ---------- language and script ----------

def test_hi_in_survey_in_english_is_rejected(insight, fake_llm):
    fake_llm.draft = GOOD_EN
    r = pipeline.process(insight, "hi-IN")
    assert r["status"] == "rejected"
    assert r["handoff"] is None
    assert any("Devanagari" in p for p in r["check"]["deterministic"])


def test_en_in_survey_with_devanagari_is_rejected(insight, fake_llm):
    fake_llm.draft = GOOD_HI
    r = pipeline.process(insight, "en-IN")
    assert r["status"] == "rejected"
    assert r["handoff"] is None
    assert any("Devanagari" in p for p in r["check"]["deterministic"])


def test_hindi_survey_in_hindi_is_scheduled(insight, fake_llm):
    fake_llm.draft = GOOD_HI
    r = pipeline.process(insight, "hi-IN")
    assert r["status"] == "scheduled"
    assert r["survey"]["language"] == "hi-IN"


# ---------- insights that must get no survey ----------

def _assert_no_survey(ins):
    r = pipeline.process(ins, "en-IN")  # any model call would fail via the no_bedrock fixture
    assert r["status"] == "no_survey"
    assert r["survey"] is None and r["handoff"] is None
    assert r["decision"]["rule"] == "R1"
    assert data.schema_errors("no_survey", r["no_survey"]) == []


def test_junk_rows_from_dataset_get_no_survey():
    junk = [i for i in data.insights() if i.get("quality_flag") == "junk"]
    assert len(junk) == 723
    for ins in junk[:25]:
        _assert_no_survey(ins)
    assert all(rules.decide(i).rule == "R1" for i in junk)


def test_casual_conversation_gets_no_survey(insight):
    insight["decision_episode_type"] = "casual"
    _assert_no_survey(insight)


def test_no_crop_and_no_concern_gets_no_survey(insight):
    insight["asset"] = {"name": None, "category": None, "growth_stage": None}
    insight["concern"] = None
    _assert_no_survey(insight)


def test_junk_detection_does_not_use_quality_flag(insight):
    insight["quality_flag"] = "junk"  # the label alone must not decide; the content is clean
    assert rules.decide(insight).survey is True
