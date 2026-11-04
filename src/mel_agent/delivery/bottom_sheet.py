"""Render a survey as the app/web bottom sheet (bottom_sheet.schema.json)."""

from __future__ import annotations

from typing import Any

_LABELS = {
    "en-IN": {"title": "A quick question about your recent advice", "skip": "Skip", "close": "Close",
              "thank_you": "Thank you. Your answers help FarmerChat give better advice.", "step": "{n} of {total}"},
    "hi-IN": {"title": "आपकी हाल की सलाह पर एक छोटा सवाल", "skip": "छोड़ें", "close": "बंद करें",
              "thank_you": "धन्यवाद। आपके जवाब FarmerChat को बेहतर सलाह देने में मदद करते हैं।", "step": "{total} में {n}"},
}


def render_bottom_sheet(survey: dict[str, Any], channel: str = "app") -> dict[str, Any]:
    if channel not in ("app", "web"):
        raise ValueError("bottom sheets exist only for the app and web chat")
    labels = _LABELS.get(survey.get("language", "en-IN"), _LABELS["en-IN"])
    steps = []
    items = survey["items"]
    for n, item in enumerate(items, start=1):
        if item["type"] == "survey-scale":
            lo, hi = int(item["scale_min"]), int(item["scale_max"])
            options = [{"label": str(v), "answer": v} for v in range(lo, hi + 1)]
        else:
            options = [{"label": o["label"], "answer": o["value"]} for o in item["options"]]
        steps.append({"step": n, "step_label": labels["step"].format(n=n, total=len(items)), "item_id": item["item_id"],
                      "question_type": item["type"], "question": item["prompt"], "options": options[:10]})
    return {
        "presentation": {
            "type": "bottom_sheet",
            "opens_when": ["push_tapped", "next_app_open"] if channel == "app" else ["next_web_visit"],
            "waits_for": ["answer_finished_streaming", "no_typing_for_5_seconds", "no_call_in_progress"],
            "one_question_per_step": True, "steps_total": len(items), "can_skip": True, "can_close": True, "swipe_down_closes": True,
        },
        "sheet": {"title": labels["title"], "skip_label": labels["skip"], "close_label": labels["close"], "steps": steps,
                  "thank_you": labels["thank_you"]},
    }
