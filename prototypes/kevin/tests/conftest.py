"""Shared fixtures. Every test runs offline: real Bedrock calls are blocked, and tests that
need a model use FakeLLM, which stands in for mel_agent.llm.call_tool."""
import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mel_agent import data, llm, rules  # noqa: E402

GOOD_EN = {
    "skip": False,
    "rationale": "Direct-action pest advice with a 2-day window. Check the spray and the aphids.",
    "items": [
        {"item_id": "q1", "type": "survey-single-select", "prompt": "Did you spray your mustard for the aphids?",
         "options": [{"value": "yes", "label": "Yes"}, {"value": "not_yet", "label": "Not yet"},
                     {"value": "no", "label": "No"}]},
        {"item_id": "q2", "type": "survey-single-select", "prompt": "How is your mustard now?",
         "options": [{"value": "better", "label": "Better"},
                     {"value": "same", "label": "Same", "follow_up": "advice_did_not_work"},
                     {"value": "worse", "label": "Worse", "follow_up": "crop_or_animal_damaged"}]},
    ],
}

GOOD_HI = {
    "skip": False,
    "rationale": "Direct-action pest advice with a 2-day window. Check the spray and the aphids.",
    "items": [
        {"item_id": "q1", "type": "survey-single-select", "prompt": "क्या आपने सरसों पर माहू के लिए छिड़काव किया?",
         "options": [{"value": "yes", "label": "हाँ"}, {"value": "not_yet", "label": "अभी नहीं"},
                     {"value": "no", "label": "नहीं"}]},
        {"item_id": "q2", "type": "survey-single-select", "prompt": "अब आपकी सरसों कैसी है?",
         "options": [{"value": "better", "label": "पहले से बेहतर"},
                     {"value": "same", "label": "पहले जैसी", "follow_up": "advice_did_not_work"},
                     {"value": "worse", "label": "पहले से खराब", "follow_up": "crop_or_animal_damaged"}]},
    ],
}

GOOD_VERDICT = {"relevance_score": 0.85, "gives_new_advice": False, "contradicts_advice": False,
                "asks_personal_info": False, "language_correct": True, "issues": []}


class FakeLLM:
    """Answers write_survey with `draft` and review_survey with `verdict`. Records every call."""

    def __init__(self, draft=None, verdict=None):
        self.draft = copy.deepcopy(draft or GOOD_EN)
        self.verdict = copy.deepcopy(verdict or GOOD_VERDICT)
        self.calls = []

    def __call__(self, model, system, user, tool_name, tool_description, schema, usage, max_tokens=1500,
                 temperature=None):
        self.calls.append(tool_name)
        usage.add(model, 100, 50, 0.0)
        if tool_name == "write_survey":
            return copy.deepcopy(self.draft)
        if tool_name == "review_survey":
            return copy.deepcopy(self.verdict)
        raise AssertionError(f"unexpected tool {tool_name}")


@pytest.fixture(autouse=True)
def no_bedrock(monkeypatch):
    """Blocks real model calls in every test. Tests that need a model install FakeLLM on top."""
    def blocked(*a, **k):
        raise AssertionError("a real LLM call was attempted in an offline test")
    monkeypatch.setattr(llm, "call_tool", blocked)
    monkeypatch.setattr(llm, "_client", blocked)


@pytest.fixture
def fake_llm(monkeypatch):
    fake = FakeLLM()
    monkeypatch.setattr(llm, "call_tool", fake)
    return fake


@pytest.fixture
def insight():
    """Digital Green's worked mustard aphid insight: clean, direct_action, gets a survey (R8)."""
    return copy.deepcopy(data.scenario_examples()[0]["insight"])


def make_survey(insight, items, language="en-IN", send_window=None):
    d = rules.decide(insight)
    return {
        "survey_id": rules.survey_id_for([insight["insight_id"]]),
        "farmer_id": insight["farmer_id"],
        "source_insight_ids": [insight["insight_id"]],
        "language": language,
        "send_window": send_window or d.send_window,
        "items": copy.deepcopy(items),
        "rationale": "Test survey.",
    }
