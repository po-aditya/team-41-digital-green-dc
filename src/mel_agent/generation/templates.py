"""Deterministic survey templates in en-IN and hi-IN, expressed as question intents.

One intent list per resolution type, mirroring the question shapes in the
pack's worked scenarios and golden items. Rendering (wording, options, labels)
is done by generation/catalog.py, so templates and model output go through the
same constrained path. Hindi text is fixed catalogue text written for the
hackathon, not machine translation; its quality has not been checked by a
Hindi-speaking reviewer (see README).
"""

from __future__ import annotations

from typing import Any

from mel_agent.generation.catalog import ASSET_GLOSSARY, supported_language
from mel_agent.generation.models import SurveyRequest

SUPPORTED_LANGUAGES = ("en-IN", "hi-IN")
# Kept for the relevance proxy and older callers: asset name -> Hindi label.
ASSET_HI = {k: v[1] for k, v in ASSET_GLOSSARY.items()}

INTENTS_BY_RESOLUTION: dict[str, list[str]] = {
    "direct_action": ["did_action", "state_now", "barrier"],
    "wait_and_monitor": ["kept_watching", "problem_growing", "need_help"],
    "do_not_act": ["held_off", "state_now"],
    "plan_created": ["plan_progress", "plan_working"],
    "escalate_to_expert": ["reached_expert", "state_after_expert"],
}


def template_items(request: SurveyRequest) -> list[dict[str, Any]]:
    """Intent items (not rendered text) for the request's resolution type."""
    if not supported_language(request.language):
        raise ValueError("unsupported language")
    intents = INTENTS_BY_RESOLUTION.get(request.resolution_type)
    if intents is None:
        raise ValueError("no template for this resolution type")
    return [{"intent": name} for name in intents]


def rationale_for(request: SurveyRequest) -> str:
    w = request.send_window
    awd = request.insight.get("action_window_days")
    awd_text = f"{awd}-day action window" if awd is not None else "no fixed action window"
    text = (f"{request.resolution_type} advice ({request.asks}) with {awd_text}; verification timing "
            f"'{w.timing}'. Ask from day {w.start_day_offset} to day {w.end_day_offset} after the advice, "
            f"when the farmer could have acted and the outcome is still fresh.")
    return text[:400]
