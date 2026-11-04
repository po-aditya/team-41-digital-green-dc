"""Deterministic SIMULATED farmer interactions.

Produces observations (raw input the channel would return, timestamps) for a
named case and passes them through ``respond.build_response``, so every derived
field still comes from the official rules. Nothing here is real farmer data:

  * response keys start with ``sim-``;
  * answers are chosen only from the survey's own options/scale;
  * free text and unrecognised speech are short placeholder phrases, marked
    in ``raw_event`` as simulated;
  * a wrong-farmer identity uses the placeholder id ``F-SIMULATED-OTHER``.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Any

from .respond import ItemObservation, build_response
from .outcomes import ResponseConfigError

SIMULATED_OTHER_FARMER = "F-SIMULATED-OTHER"
_FREE_TEXT = {"hi-IN": "पता नहीं, कल बताऊँगा", "en-IN": "Not sure, will tell tomorrow"}
_UNCLEAR_SPEECH = {"hi-IN": "हम्म... शायद", "en-IN": "Hmm... maybe"}

# Delivery failures: the message never reached the farmer.
_UNDELIVERED = {"push_token_invalid", "client_cannot_render", "wa_session_window_closed",
                "wa_undelivered", "tg_bot_blocked", "voice_no_answer", "voice_busy"}

# Cases this simulator can script. Success outcomes and invalid-input codes are
# not passed as events: build_response derives them from the scripted input.
CASES = (
    "completed", "negative_outcome", "partial", "sheet_closed_partway", "sheet_interrupted",
    "farmer_declined", "farmer_opted_out", "sheet_dismissed",
    "free_text_instead_of_choice", "keypad_out_of_range", "speech_not_understood",
    "duplicate_answer", "survey_closed", "survey_replaced", "identity_mismatch",
    "window_expired", "push_not_opened", "voice_call_dropped",
) + tuple(sorted(_UNDELIVERED))


def _ist(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + "+05:30"


def _survey_dict(survey: Any) -> dict[str, Any]:
    return survey.dump() if hasattr(survey, "dump") else survey


def choose_value(item: Mapping[str, Any], *, negative: bool = False) -> str | int:
    """A real choice from the survey: a healthy one, or one that flags follow-up."""
    if item["type"] == "survey-scale":
        if negative and item.get("follow_up_at_or_below") is not None:
            return max(item["scale_min"], item["follow_up_at_or_below"])
        return item["scale_max"]
    options = item["options"]
    if negative:
        flagged = [o for o in options if o.get("follow_up")]
        if flagged:
            return flagged[0]["value"]
    healthy = [o for o in options if not o.get("follow_up")]
    return (healthy or options)[0]["value"]


def format_raw(survey: Mapping[str, Any], item: Mapping[str, Any], value: str | int,
               channel: str) -> tuple[str, str]:
    """The (raw_input, input_kind) a channel would return for this choice."""
    sid, qid = survey["survey_id"], item["item_id"]
    is_scale = item["type"] == "survey-scale"
    if channel in ("app", "web"):
        return str(value), "sheet_tap"
    if channel == "whatsapp":
        # WhatsApp shows at most 3 reply buttons; longer choice lists use a list.
        n = (item["scale_max"] - item["scale_min"] + 1) if is_scale else len(item["options"])
        return f"{sid}|{qid}|{value}", ("list_reply" if n > 3 else "button_reply")
    if channel == "telegram":
        return f"mel|{sid}|{qid}|{value}", "callback_data"
    if channel == "voice":
        if is_scale:
            return str(value), "keypad"
        if item["type"] == "survey-confirm":
            label = next(o["label"] for o in item["options"] if o["value"] == value)
            return label, "speech"
        index = [o["value"] for o in item["options"]].index(value) + 1
        return str(index), "keypad"
    raise ResponseConfigError(f"unknown channel {channel!r}")


def _answer(survey, item, channel, *, negative=False) -> ItemObservation:
    raw, kind = format_raw(survey, item, choose_value(item, negative=negative), channel)
    return ItemObservation(shown=True, raw_input=raw, input_kind=kind)


def simulate(
    survey: Any,
    channel: str,
    case: str,
    *,
    sent_at: datetime,
    expires_at: datetime | None = None,
    delivery_attempt: int = 1,
) -> dict[str, Any]:
    """Script one simulated attempt and build its validated response record."""
    if case not in CASES:
        raise ResponseConfigError(f"simulator has no script for case {case!r}")
    s = _survey_dict(survey)
    items = s["items"]
    lang = s["language"]
    obs: dict[str, ItemObservation] = {}
    event: str | None = None
    answered_by: str | None = s["farmer_id"]
    raw_event: str | None = None

    delivered = sent_at + timedelta(minutes=1)
    opened = sent_at + timedelta(minutes=20)
    answered = sent_at + timedelta(minutes=25)
    ts = {"sent": sent_at, "delivered": delivered, "opened": opened, "answered": answered}

    if case == "completed":
        obs = {i["item_id"]: _answer(s, i, channel) for i in items}
    elif case == "negative_outcome":
        flagged = [i for i in items
                   if (i["type"] == "survey-scale" and i.get("follow_up_at_or_below") is not None)
                   or any(o.get("follow_up") for o in i.get("options", []))]
        if not flagged:
            raise ResponseConfigError("survey has no answer that flags follow-up")
        target = flagged[-1]["item_id"]
        obs = {i["item_id"]: _answer(s, i, channel, negative=i["item_id"] == target) for i in items}
    elif case in ("partial", "sheet_closed_partway", "sheet_interrupted"):
        obs = {i["item_id"]: _answer(s, i, channel) for i in items[:-1]}
        obs[items[-1]["item_id"]] = ItemObservation(shown=True)  # shown, not answered
        if case != "partial":
            event = case
            raw_event = (f"Close tapped at step {len(items)} of {len(items)} (simulated)"
                         if case == "sheet_closed_partway" else "app closed part way (simulated)")
    elif case in ("farmer_declined", "farmer_opted_out"):
        event = case
        raw_event = "simulated decline" if case == "farmer_declined" else "simulated opt-out"
    elif case == "sheet_dismissed":
        event = case
        obs = {items[0]["item_id"]: ItemObservation(shown=True)}
        raw_event = "sheet swiped down (simulated)"
    elif case in _FREE_TEXT_CASES:
        bad_kind, bad_text, attempts = _FREE_TEXT_CASES[case]
        obs = {i["item_id"]: _answer(s, i, channel) for i in items[:-1]}
        text = bad_text(items[-1], lang)
        obs[items[-1]["item_id"]] = ItemObservation(
            shown=True, raw_input=text, input_kind=bad_kind, attempts=attempts)
        raw_event = None
    elif case in ("duplicate_answer", "survey_closed", "survey_replaced"):
        event = case
        target = items[-1] if case == "duplicate_answer" else items[0]
        obs = {target["item_id"]: _answer(s, target, channel)}
        if case == "survey_closed":
            if expires_at is None:
                raise ResponseConfigError("survey_closed needs expires_at")
            ts["answered"] = expires_at  # a tap at/after expiry
    elif case == "identity_mismatch":
        answered_by = SIMULATED_OTHER_FARMER
        obs = {items[0]["item_id"]: _answer(s, items[0], channel)}
    elif case in ("window_expired", "push_not_opened"):
        event = case
        ts["opened"] = ts["answered"] = None
        answered_by = None
    elif case == "voice_call_dropped":
        event = case
        obs = {i["item_id"]: _answer(s, i, channel) for i in items[:-1]}
        ts["answered"] = None
        raw_event = "call ended during the question (simulated)"
    elif case in _UNDELIVERED:
        event = case
        ts["delivered"] = ts["opened"] = ts["answered"] = None
        answered_by = None
        raw_event = f"simulated {case}"

    if channel == "telegram":
        ts["opened"] = None  # Telegram has no read receipts

    stamps = {k: (_ist(v) if v else None) for k, v in ts.items()}
    if case in ("window_expired", "push_not_opened") and expires_at is not None:
        recorded = _ist(expires_at)
    else:
        recorded = next(stamps[k] for k in ("answered", "opened", "delivered", "sent") if stamps[k])

    return build_response(
        s,
        channel=channel,
        items=obs,
        timestamps=stamps,
        recorded_at=recorded,
        response_key=f"sim-{s['survey_id']}-{channel}-{case}-a{delivery_attempt}",
        answered_by=answered_by,
        event=event,
        delivery_attempt=delivery_attempt,
        raw_event=raw_event,
    )


def _out_of_range_key(item: Mapping[str, Any], _lang: str) -> str:
    if item["type"] == "survey-scale":
        return str(item["scale_max"] + 1)
    return str(len(item["options"]) + 1)


# case -> (input_kind, text factory, attempts). Farmer input that matches no choice.
_FREE_TEXT_CASES = {
    "free_text_instead_of_choice": ("free_text", lambda item, lang: _FREE_TEXT.get(lang, _FREE_TEXT["en-IN"]), 1),
    "keypad_out_of_range": ("keypad", _out_of_range_key, 2),
    "speech_not_understood": ("speech", lambda item, lang: _UNCLEAR_SPEECH.get(lang, _UNCLEAR_SPEECH["en-IN"]), 2),
}
