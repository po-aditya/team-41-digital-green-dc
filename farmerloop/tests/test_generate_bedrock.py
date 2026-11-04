"""Bedrock generator tests with a mocked client. No network, no AWS calls."""

import json

import pytest

from farmerloop import config
from farmerloop.generate_base import SurveyValidationError
from farmerloop.generate_bedrock import BedrockSurveyGenerator
from farmerloop.timing import compute_window
from farmerloop.validate import validate

from tests.helpers import make_insight


class MockClient:
    def __init__(self, text):
        self.text = text
        self.calls = []

    def converse(self, **kwargs):
        self.calls.append(kwargs)
        return {"output": {"message": {"content": [{"text": self.text}]}}}


def _items(*items):
    return json.dumps({"items": list(items), "rationale": "check outcome"}, ensure_ascii=False)


CONFIRM_HI = {
    "item_id": "q1",
    "type": "survey-confirm",
    "prompt": "क्या आपने छिड़काव किया?",
    "options": [{"value": "yes", "label": "हाँ"}, {"value": "no", "label": "नहीं"}],
}


def _run(text, lang="hi-IN"):
    ins = make_insight(conversation_language=lang)
    w = compute_window(ins.created_at, ins.verification.timing, ins.action_window_days)
    client = MockClient(text)
    return BedrockSurveyGenerator(client=client).generate(ins, w), client


def test_valid_response_is_schema_valid_and_uses_configured_model():
    survey, client = _run(_items(CONFIRM_HI))
    assert validate("survey", survey.dump()) == []
    assert survey.language == "hi-IN"
    assert client.calls[0]["modelId"] == config.BEDROCK_MODEL_ID


def test_code_fenced_response_accepted():
    survey, _ = _run("```json\n" + _items(CONFIRM_HI) + "\n```")
    assert validate("survey", survey.dump()) == []


def test_model_self_eval_claims_are_ignored():
    payload = json.loads(_items(CONFIRM_HI))
    payload["self_eval"] = {"relevance_score": 1.0, "gives_new_advice": False}
    survey, _ = _run(json.dumps(payload, ensure_ascii=False))
    assert "relevance_score" not in survey.self_eval.dump()


def _bad_label():
    item = json.loads(json.dumps(CONFIRM_HI))
    item["options"][0]["label"] = "हाँ, मैंने पूरी तरह से छिड़काव किया"  # > 20 code points
    return _items(item)


def _bad_follow_up():
    item = json.loads(json.dumps(CONFIRM_HI))
    item["options"][1]["follow_up"] = "made_up_code"
    return _items(item)


def _unsafe_advice():
    item = json.loads(json.dumps(CONFIRM_HI))
    item["prompt"] = "Did you spray? You should apply more urea next week."
    return _items(item)


@pytest.mark.parametrize(
    "text",
    [
        pytest.param(_bad_label(), id="label-too-long-not-truncated"),
        pytest.param(_bad_follow_up(), id="follow-up-not-in-enum"),
        pytest.param(_unsafe_advice(), id="new-advice-flagged"),
        pytest.param("Sure! {items: [broken", id="malformed-json"),
        pytest.param("no json here at all", id="no-json-object"),
        pytest.param(json.dumps({"items": [], "rationale": "r"}), id="empty-items"),
    ],
)
def test_bad_model_output_raises(text):
    with pytest.raises(SurveyValidationError):
        _run(text)
