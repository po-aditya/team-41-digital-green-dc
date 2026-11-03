"""Builds answer records that follow json/schemas/response.schema.json."""
from datetime import timedelta

from . import data
from .rules import fmt_ts

SHEET_CHANNELS = {"app", "web"}
INPUT_KIND = {"app": "sheet_tap", "web": "sheet_tap", "whatsapp": "button_reply",
              "telegram": "callback_data", "voice": "keypad"}
RAW_EVENT = {
    "window_expired": "no answer before the survey expired",
    "farmer_declined": "farmer said not now",
    "farmer_opted_out": "farmer asked for no more surveys",
    "push_token_invalid": "push address no longer works",
    "client_cannot_render": "this version cannot show the survey sheet",
    "wa_session_window_closed": "outside the 24 hour session window",
    "wa_undelivered": "whatsapp reported the message failed",
    "tg_bot_blocked": "farmer blocked the bot",
    "voice_no_answer": "no answer on the call",
    "voice_busy": "line busy",
    "sheet_dismissed": "sheet closed before any answer",
    "push_not_opened": "notification never opened",
}
# Failures the simulator can produce, with how often they happen on each channel.
SIM_FAILURES = {
    "app": {"push_not_opened": 6, "sheet_dismissed": 4, "push_token_invalid": 3, "client_cannot_render": 1, "farmer_opted_out": 1},
    "web": {"window_expired": 6, "sheet_dismissed": 4, "client_cannot_render": 2, "farmer_opted_out": 1},
    "whatsapp": {"window_expired": 5, "wa_session_window_closed": 3, "wa_undelivered": 2, "farmer_declined": 3, "farmer_opted_out": 1},
    "telegram": {"window_expired": 5, "tg_bot_blocked": 3, "farmer_declined": 3, "farmer_opted_out": 1},
    "voice": {"voice_no_answer": 6, "voice_busy": 3, "farmer_declined": 3, "farmer_opted_out": 1},
}


def _failure(code):
    return data.outcome_codes()["failures"][code]


def follow_ups(survey, answers):
    """Follow-up reasons triggered by accepted answers."""
    reasons = []
    for it in survey["items"]:
        v = answers.get(it["item_id"])
        if v is None:
            continue
        if it["type"] == "survey-scale":
            if it.get("follow_up_at_or_below") is not None and int(v) <= it["follow_up_at_or_below"]:
                reasons.append(it["follow_up_reason"])
        else:
            for o in it.get("options", []):
                if o["value"] == v and o.get("follow_up"):
                    reasons.append(o["follow_up"])
    return list(dict.fromkeys(reasons))


def answered_record(survey, channel, attempt, sent_at, answered_at, answers, sheet_closed_early=False):
    """A record for answers the farmer gave (all, some, or with a bad outcome)."""
    items = []
    for it in survey["items"]:
        v = answers.get(it["item_id"])
        items.append({"item_id": it["item_id"], "item_type": it["type"],
                      "result": "answered" if v is not None else "skipped", "value": v,
                      "raw_input": None if v is None else str(v)[:256],
                      "input_kind": None if v is None else INPUT_KIND[channel], "attempts": 1 if v is not None else 0})
    reasons = follow_ups(survey, answers)
    complete = all(i["result"] == "answered" for i in items)
    status = "negative_outcome" if reasons else ("completed" if complete else "partial")
    sheet = None
    if channel in SHEET_CHANNELS:
        sheet = "finished" if complete or not sheet_closed_early else "closed_partway"
    return {
        "response_key": f"rk-{survey['survey_id']}-{channel}-{attempt}",
        "survey_id": survey["survey_id"], "farmer_id": survey["farmer_id"],
        "source_insight_ids": survey["source_insight_ids"], "channel": channel, "language": survey["language"],
        "status": status, "failure_code": None, "sheet_outcome": sheet,
        "answers": {k: v for k, v in answers.items() if v is not None}, "items": items, "complete": complete,
        "delivery_attempt": attempt,
        "timestamps": {"sent": fmt_ts(sent_at), "delivered": fmt_ts(sent_at + timedelta(minutes=1)),
                       "opened": None if channel == "telegram" else fmt_ts(answered_at - timedelta(minutes=2)),
                       "answered": fmt_ts(answered_at)},
        "recorded_at": fmt_ts(answered_at), "answered_by": survey["farmer_id"], "raw_event": None,
        "retry_decision": "none", "retry_after_minutes": None, "counts_toward_cap": True,
        "farmerchat_reply": {"http_status": 201, "outcome": "accepted"},
        "needs_follow_up": bool(reasons), "follow_up_reasons": reasons,
    }


def failure_record(survey, channel, attempt, sent_at, code):
    f = _failure(code)
    delivered = f["status"] != "delivery_failed"
    opened = code in ("farmer_declined", "farmer_opted_out", "sheet_dismissed") and channel != "telegram"
    items = [{"item_id": it["item_id"], "item_type": it["type"], "result": "not_reached", "value": None,
              "raw_input": None, "input_kind": None, "attempts": 0} for it in survey["items"]]
    if code == "sheet_dismissed" or (code == "window_expired" and channel not in SHEET_CHANNELS):
        items[0]["result"] = "skipped"
    sheet = None
    if channel in SHEET_CHANNELS:
        sheet = "dismissed" if code in ("sheet_dismissed", "farmer_opted_out") else "never_opened"
    return {
        "response_key": f"rk-{survey['survey_id']}-{channel}-{attempt}",
        "survey_id": survey["survey_id"], "farmer_id": survey["farmer_id"],
        "source_insight_ids": survey["source_insight_ids"], "channel": channel, "language": survey["language"],
        "status": f["status"], "failure_code": code, "sheet_outcome": sheet, "answers": {}, "items": items,
        "complete": False, "delivery_attempt": attempt,
        "timestamps": {"sent": fmt_ts(sent_at), "delivered": fmt_ts(sent_at + timedelta(minutes=1)) if delivered else None,
                       "opened": fmt_ts(sent_at + timedelta(minutes=20)) if opened else None, "answered": None},
        "recorded_at": fmt_ts(sent_at + timedelta(minutes=2)), "answered_by": None, "raw_event": RAW_EVENT.get(code),
        "retry_decision": f["retry_decision"], "retry_after_minutes": f["retry_after_minutes"],
        "counts_toward_cap": f["counts_toward_cap"], "farmerchat_reply": None,
        "needs_follow_up": False, "follow_up_reasons": [],
    }
