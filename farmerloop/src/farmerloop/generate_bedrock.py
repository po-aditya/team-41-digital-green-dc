"""Real Amazon Bedrock survey generator (Converse API).

Asks a Bedrock model to write a short, schema-shaped survey in the farmer's
language, then re-shapes, validates and safety-audits the result via
``finalize_survey``. If the model output cannot be parsed, has bad labels or
follow-up codes, fails the official schema, or trips the safety audit, we raise
``SurveyValidationError`` so the caller can fall back to the deterministic
generator rather than shipping an unsafe or invalid survey.

Kept intentionally small: one Converse call, JSON-only response, no tools. We
never trust the model's own safety/quality claims - self_eval is recomputed
from the actual survey by finalize_survey.
"""

from __future__ import annotations

import json
from typing import Any

from . import config
from .generate_base import (
    SurveyValidationError,
    finalize_survey,
    new_survey_scaffold,
    resolve_language,
    validate_follow_up,
    validate_label,
)
from .models import Insight, Item, Option, Survey
from .timing import Window

_SYSTEM = (
    "You write very short follow-up surveys for smallholder farmers in Bihar, "
    "India, about agricultural advice they already received from FarmerChat. "
    "Rules you must follow exactly:\n"
    "- Ask ONLY about the advice already given. NEVER give new advice.\n"
    "- NEVER ask for personal information.\n"
    "- Write 1 to 2 questions. Each answerable with a single tap.\n"
    "- Write entirely in the requested language.\n"
    "- Answer labels must be at most 20 characters.\n"
    "- Respond with JSON only, no prose, no code fences."
)

_RESPONSE_SHAPE = {
    "items": [
        {
            "item_id": "q1",
            "type": "survey-confirm",
            "prompt": "<question text in the target language>",
            "options": [
                {"value": "yes", "label": "<=20 chars"},
                {"value": "no", "label": "<=20 chars"},
            ],
        },
        {
            "item_id": "q2",
            "type": "survey-single-select",
            "prompt": "<outcome question in the target language>",
            "options": [
                {"value": "better", "label": "<=20 chars"},
                {"value": "same", "label": "<=20 chars"},
                {"value": "worse", "label": "<=20 chars",
                 "follow_up": "crop_or_animal_damaged"},
            ],
        },
    ],
    "rationale": "<one English sentence: why this survey, why now>",
}


def _build_prompt(insight: Insight, language: str) -> str:
    return (
        f"Target language (BCP-47): {language}\n"
        f"Crop/animal: {insight.asset.name}\n"
        f"Concern: {insight.concern}\n"
        f"Resolution type: {insight.resolution_type}\n"
        f"What the farmer asked: {insight.query_summary}\n"
        f"Advice given: {insight.advice_summary}\n\n"
        "Write the follow-up survey as JSON in exactly this shape "
        "(1 or 2 items; omit follow_up unless the answer is a clearly bad "
        "outcome; allowed follow_up values: advice_did_not_work, "
        "crop_or_animal_damaged, could_not_get_input, could_not_reach_expert):\n"
        + json.dumps(_RESPONSE_SHAPE, ensure_ascii=False, indent=2)
    )


class BedrockSurveyGenerator:
    """Survey generator backed by Amazon Bedrock Converse."""

    name = "bedrock"

    def __init__(self, model_id: str | None = None, region: str | None = None,
                 client: Any = None):
        self.model_id = model_id or config.BEDROCK_MODEL_ID
        self.region = region or config.BEDROCK_REGION
        self._client = client  # injectable for tests/mocks.

    def _bedrock(self) -> Any:
        if self._client is None:
            import boto3  # lazy import so offline tests never need boto3/creds.
            self._client = boto3.client("bedrock-runtime", region_name=self.region)
        return self._client

    def _invoke(self, system: str, prompt: str) -> str:
        resp = self._bedrock().converse(
            modelId=self.model_id,
            system=[{"text": system}],
            messages=[{"role": "user", "content": [{"text": prompt}]}],
            inferenceConfig={"maxTokens": 600, "temperature": 0.2},
        )
        parts = resp["output"]["message"]["content"]
        return "".join(p.get("text", "") for p in parts).strip()

    @staticmethod
    def _parse_json(text: str) -> dict[str, Any]:
        t = text.strip()
        if t.startswith("```"):
            t = t.strip("`")
        start, end = t.find("{"), t.rfind("}")
        if start == -1 or end == -1:
            raise SurveyValidationError(
                f"no JSON object in model output: {text[:120]!r}"
            )
        try:
            return json.loads(t[start:end + 1])
        except json.JSONDecodeError as exc:
            raise SurveyValidationError(f"model output is not valid JSON: {exc}")

    def _to_items(self, data: dict[str, Any]) -> list[Item]:
        raw_items = data.get("items")
        if not isinstance(raw_items, list) or not raw_items:
            raise SurveyValidationError("model returned no items")
        items: list[Item] = []
        for raw_item in raw_items[:3]:
            itype = raw_item.get("type")
            prompt = raw_item.get("prompt")
            if not prompt:
                raise SurveyValidationError("item missing prompt")
            opts: list[Option] | None = None
            if itype != "survey-scale":
                opts = []
                for o in raw_item.get("options", []):
                    opts.append(
                        Option(
                            value=o["value"],
                            label=validate_label(o["label"]),  # no truncation
                            follow_up=validate_follow_up(o.get("follow_up")),
                        )
                    )
            items.append(
                Item(item_id=raw_item["item_id"], type=itype, prompt=prompt, options=opts)
            )
        return items

    def generate(self, insight: Insight, window: Window) -> Survey:
        language = resolve_language(insight)
        raw = self._invoke(_SYSTEM, _build_prompt(insight, language))
        data = self._parse_json(raw)
        items = self._to_items(data)

        scaffold = new_survey_scaffold(insight, window, language)
        survey = Survey(
            **scaffold,
            items=items,
            rationale=(data.get("rationale")
                       or f"Bedrock follow-up for {insight.resolution_type}."),
            self_eval=None,  # recomputed honestly by finalize_survey.
        )
        # Validate against the official schema + run the safety audit. Raises
        # on any problem so the caller falls back to the fake generator.
        return finalize_survey(survey)
