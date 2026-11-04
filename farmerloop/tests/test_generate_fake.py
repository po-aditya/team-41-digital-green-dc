"""Fake generator and shared safety-gate tests."""

import pytest

from farmerloop.generate_base import (
    MAX_LABEL_LEN,
    SurveyValidationError,
    audit_survey_safety,
    finalize_survey,
)
from farmerloop.generate_fake import FakeSurveyGenerator
from farmerloop.models import Item, Option, Survey
from farmerloop.timing import compute_window
from farmerloop.validate import validate

from tests.helpers import make_insight

RESOLUTIONS = [
    "direct_action",
    "wait_and_monitor",
    "do_not_act",
    "plan_created",
    "escalate_to_expert",
]


def _generate(**over):
    ins = make_insight(**over)
    w = compute_window(ins.created_at, ins.verification.timing, ins.action_window_days)
    return FakeSurveyGenerator().generate(ins, w)


@pytest.mark.parametrize("lang", ["en-IN", "hi-IN"])
@pytest.mark.parametrize("res", RESOLUTIONS)
def test_all_resolutions_and_languages_schema_valid(lang, res):
    s = _generate(conversation_language=lang, resolution_type=res)
    assert validate("survey", s.dump()) == []
    assert s.language == lang
    for item in s.items:
        for opt in item.options or []:
            assert 1 <= len(opt.label) <= MAX_LABEL_LEN


def test_hindi_survey_text_is_devanagari():
    s = _generate(conversation_language="hi-IN")
    assert any("\u0900" <= ch <= "\u097f" for ch in s.items[0].prompt)


def test_unsupported_language_falls_back_consistently():
    s = _generate(conversation_language="ta-IN")
    assert s.language == "en-IN"
    assert s.items[0].prompt.isascii()


def test_only_clearly_bad_outcome_flags_follow_up():
    direct = _generate(resolution_type="direct_action").items[1].options
    assert {o.value: o.follow_up for o in direct} == {
        "better": None,
        "same": None,
        "worse": "crop_or_animal_damaged",
    }
    monitor = _generate(resolution_type="wait_and_monitor").items[1].options
    assert {o.value: o.follow_up for o in monitor} == {
        "no": None,
        "same": None,
        "yes": "crop_or_animal_damaged",
    }


def test_self_eval_is_audit_derived_without_relevance_score():
    se = _generate().self_eval.dump()
    assert se == {"schema_valid": True, "gives_new_advice": False, "asks_personal_info": False}


def _one_q(prompt):
    return Survey(
        survey_id="S-1234567890",
        farmer_id="F-1",
        source_insight_ids=["I-1"],
        language="en-IN",
        send_window={
            "not_before": "2026-12-06T07:00:00+05:30",
            "not_after": "2026-12-09T19:00:00+05:30",
        },
        items=[
            Item(
                item_id="q1",
                type="survey-confirm",
                prompt=prompt,
                options=[Option(value="yes", label="Yes"), Option(value="no", label="No")],
            )
        ],
        rationale="t",
    )


@pytest.mark.parametrize(
    "prompt",
    [
        "Did you apply the treatment you were advised?",
        "Did you spray your mustard for the aphids?",
        "क्या आपने दी गई सलाह पर अमल किया?",
    ],
)
def test_legitimate_follow_ups_not_flagged(prompt):
    audit = audit_survey_safety(_one_q(prompt))
    assert not audit.review_required, audit.flags


@pytest.mark.parametrize(
    "prompt",
    [
        "Did you spray? You should apply more urea next week.",
        "You must apply the insecticide twice this week.",
        "What is your phone number so we can call you?",
        "आपका नाम क्या है?",
    ],
)
def test_unsafe_prompts_rejected(prompt):
    with pytest.raises(SurveyValidationError):
        finalize_survey(_one_q(prompt))
