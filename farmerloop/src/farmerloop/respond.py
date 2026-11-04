"""Build schema-valid farmer response records from what actually happened.

The caller supplies OBSERVATIONS only: which survey, which channel, what the
farmer did with each question (shown or not, the raw input the channel
returned), timestamps, and any channel/server event that ended the attempt
(e.g. ``voice_no_answer``, ``duplicate_answer``). Everything else is DERIVED:

  * answer values, interpreted from the raw input and checked against the
    survey's own options or scale;
  * status, failure_code, retry_decision, retry_after_minutes and
    counts_toward_cap, from json/rules/outcome_codes.json;
  * sheet_outcome, answers, complete, farmerchat_reply, needs_follow_up and
    follow_up_reasons;
  * provenance (survey_id, farmer_id, source_insight_ids, language), copied
    from the survey, never typed in by the caller.

Two kinds of "invalid" are kept apart:
  * invalid FARMER input (typed text instead of a tap, a keypad digit with no
    answer behind it, speech that matches no choice) is a normal outcome: the
    item is marked ``invalid`` and the record gets status ``invalid_input`` with
    the retry behaviour the rules give for that channel;
  * invalid PROGRAM input (unknown question id, a channel that cannot produce
    that input or event, a button payload for another survey, contradictory
    observations) raises ``ResponseConfigError``.

Every record is validated against response.schema.json before it is returned.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from . import outcomes
from .outcomes import SHEET_CHANNELS, ResponseConfigError, OutcomeRule
from .validate import validate

# Which raw input kinds each channel can return.
INPUT_KINDS_BY_CHANNEL: dict[str, frozenset[str]] = {
    "app": frozenset({"sheet_tap"}),
    "web": frozenset({"sheet_tap"}),
    "whatsapp": frozenset({"button_reply", "list_reply", "free_text"}),
    "telegram": frozenset({"callback_data", "free_text"}),
    "voice": frozenset({"keypad", "speech"}),
}

# Farmer-originated input kinds: these can legitimately fail to match a choice.
# Their failure codes come from outcome_codes.json.
_FARMER_INVALID_CODE = {
    "free_text": "free_text_instead_of_choice",
    "keypad": "keypad_out_of_range",
    "speech": "speech_not_understood",
}

# Outcomes derived from observations; the caller must not pass them as events.
_DERIVED_ONLY_CODES = set(_FARMER_INVALID_CODE.values()) | {"identity_mismatch"}

# Statuses where an answer arrived but is not stored.
_DISCARD_STATUSES = {"duplicate", "stale", "identity_mismatch"}

# Events after which the farmer cannot have answered anything on this attempt.
# (voice_call_dropped keeps answers given before the cut, so it is not here.)
_NO_ANSWER_EVENTS = {
    "window_expired", "push_not_opened", "sheet_dismissed",
    "push_token_invalid", "client_cannot_render", "wa_session_window_closed",
    "wa_undelivered", "tg_bot_blocked", "voice_no_answer", "voice_busy",
}

# Sheet outcome for app/web, from the meaning of each event in outcome_codes.json:
# never shown -> never_opened; closed before answering -> dismissed.
_SHEET_NEVER_OPENED = {"push_token_invalid", "client_cannot_render",
                       "push_not_opened", "window_expired"}
_SHEET_DISMISSED = {"sheet_dismissed", "farmer_opted_out"}

_TIMESTAMP_KEYS = ("sent", "delivered", "opened", "answered")


@dataclass
class ItemObservation:
    """What happened to one survey question on this attempt.

    shown:     the question was put in front of the farmer.
    raw_input: what the channel returned (tapped option, button id, callback
               data, keypad digit, spoken words or typed text), or None.
    input_kind: how it arrived; required when raw_input is given.
    attempts:  how many times it was asked. Defaults to 1 if shown, else 0.
    """

    shown: bool
    raw_input: str | None = None
    input_kind: str | None = None
    attempts: int | None = None


# --------------------------------------------------------------------------
# Raw input interpretation.
# --------------------------------------------------------------------------
def _is_scale(item: Mapping[str, Any]) -> bool:
    return item["type"] == "survey-scale"


def _scale_value(item: Mapping[str, Any], text: str) -> int | None:
    t = text.strip()
    if not t.isdigit():
        return None
    v = int(t)
    return v if item["scale_min"] <= v <= item["scale_max"] else None


def _option_values(item: Mapping[str, Any]) -> list[str]:
    return [o["value"] for o in item.get("options", [])]


def _structured_value(item: Mapping[str, Any], value_text: str, where: str) -> str | int:
    """A value carried by a button/sheet/callback we generated ourselves.

    These can only carry choices we offered, so a mismatch is a program error.
    """
    if _is_scale(item):
        v = _scale_value(item, value_text)
        if v is None:
            raise ResponseConfigError(
                f"{where}: {value_text!r} is not on the {item['item_id']} scale "
                f"{item['scale_min']}..{item['scale_max']}"
            )
        return v
    if value_text not in _option_values(item):
        raise ResponseConfigError(
            f"{where}: {value_text!r} is not an option of {item['item_id']} "
            f"(options: {_option_values(item)})"
        )
    return value_text


def _payload_value(survey_id: str, item: Mapping[str, Any], raw: str, kind: str) -> str | int:
    parts = raw.split("|")
    if kind == "callback_data":
        if len(parts) != 4 or parts[0] != "mel":
            raise ResponseConfigError(f"malformed Telegram callback_data {raw!r}")
        parts = parts[1:]
    if len(parts) != 3:
        raise ResponseConfigError(f"malformed {kind} payload {raw!r}")
    sid, qid, value_text = parts
    if sid != survey_id or qid != item["item_id"]:
        raise ResponseConfigError(
            f"{kind} payload {raw!r} is for {sid}/{qid}, not {survey_id}/{item['item_id']}"
        )
    return _structured_value(item, value_text, f"{kind} {raw!r}")


def interpret(survey_id: str, item: Mapping[str, Any], raw_input: str,
              input_kind: str) -> str | int | None:
    """Turn raw channel input into an answer value.

    Returns None when FARMER input matches no choice (a normal invalid answer).
    Raises ResponseConfigError for payloads only our own system could produce.
    """
    if input_kind == "sheet_tap":
        return _structured_value(item, raw_input, f"sheet_tap {raw_input!r}")
    if input_kind in ("button_reply", "list_reply", "callback_data"):
        return _payload_value(survey_id, item, raw_input, input_kind)
    if input_kind == "free_text":
        return None  # typed text is never accepted as a choice
    if input_kind == "keypad":
        if _is_scale(item):
            return _scale_value(item, raw_input)
        t = raw_input.strip()
        options = _option_values(item)
        if t.isdigit() and 1 <= int(t) <= len(options):
            return options[int(t) - 1]  # keys are numbered in option order
        return None
    if input_kind == "speech":
        if _is_scale(item):
            return _scale_value(item, raw_input)
        spoken = raw_input.strip().casefold()
        for opt in item.get("options", []):
            if spoken in (opt["label"].strip().casefold(), opt["value"].casefold()):
                return opt["value"]
        return None
    raise ResponseConfigError(f"unknown input_kind {input_kind!r}")


def follow_up_reason(item: Mapping[str, Any], value: str | int) -> str | None:
    """The follow-up reason an ACCEPTED answer carries under the survey's own rules."""
    if _is_scale(item):
        threshold = item.get("follow_up_at_or_below")
        if threshold is not None and isinstance(value, int) and value <= threshold:
            return item["follow_up_reason"]
        return None
    for opt in item.get("options", []):
        if opt["value"] == value:
            return opt.get("follow_up")
    return None


# --------------------------------------------------------------------------
# Record builder.
# --------------------------------------------------------------------------
def _survey_dict(survey: Any) -> dict[str, Any]:
    data = survey.dump() if hasattr(survey, "dump") else survey
    for key in ("survey_id", "farmer_id", "source_insight_ids", "language", "items"):
        if key not in data:
            raise ResponseConfigError(f"survey is missing {key!r}")
    ids = [i["item_id"] for i in data["items"]]
    if len(set(ids)) != len(ids):
        raise ResponseConfigError(f"survey {data['survey_id']} has duplicate item ids")
    return data


def _check_event(channel: str, event: str | None) -> OutcomeRule | None:
    if event is None:
        return None
    if event in _DERIVED_ONLY_CODES:
        raise ResponseConfigError(
            f"{event!r} is derived from the observations, not passed as an event "
            "(give the farmer's raw input, or a different answered_by)"
        )
    if event not in outcomes.failure_codes() and event not in outcomes.sheet_cases():
        raise ResponseConfigError(f"unknown event {event!r}")
    reason = outcomes.not_applicable(channel, event)
    if reason:
        raise ResponseConfigError(f"{event!r} cannot happen on {channel}: {reason}")
    rule = outcomes.event_rule(event)
    if channel not in rule.channels:
        raise ResponseConfigError(
            f"{event!r} cannot happen on {channel} (allowed: {sorted(rule.channels)})"
        )
    return rule


def _check_observation(channel: str, item_id: str, obs: ItemObservation) -> int:
    """Validate one observation; return its attempts count."""
    if not obs.shown:
        if obs.raw_input is not None or obs.input_kind is not None:
            raise ResponseConfigError(f"{item_id}: input given for a question that was not shown")
        attempts = 0 if obs.attempts is None else obs.attempts
        if attempts != 0:
            raise ResponseConfigError(f"{item_id}: a question not shown has 0 attempts")
        return 0
    if obs.raw_input is None and obs.input_kind is not None:
        raise ResponseConfigError(f"{item_id}: input_kind given without raw_input")
    if obs.raw_input is not None:
        if obs.input_kind not in INPUT_KINDS_BY_CHANNEL[channel]:
            raise ResponseConfigError(
                f"{item_id}: {channel} cannot return input_kind {obs.input_kind!r} "
                f"(allowed: {sorted(INPUT_KINDS_BY_CHANNEL[channel])})"
            )
    attempts = 1 if obs.attempts is None else obs.attempts
    if not 1 <= attempts <= 5:
        raise ResponseConfigError(f"{item_id}: attempts must be 1..5 for a shown question")
    return attempts


def build_response(
    survey: Any,
    *,
    channel: str,
    items: Mapping[str, ItemObservation],
    timestamps: Mapping[str, str | None],
    recorded_at: str,
    response_key: str,
    answered_by: str | None,
    event: str | None = None,
    delivery_attempt: int = 1,
    raw_event: str | None = None,
    question_type: str | None = None,
) -> dict[str, Any]:
    """Build and validate one response record. See module docstring."""
    s = _survey_dict(survey)
    if channel not in INPUT_KINDS_BY_CHANNEL:
        raise ResponseConfigError(f"unknown channel {channel!r}")

    survey_items = {i["item_id"]: i for i in s["items"]}
    unknown = set(items) - set(survey_items)
    if unknown:
        raise ResponseConfigError(f"items not in survey {s['survey_id']}: {sorted(unknown)}")

    ts = {k: timestamps.get(k) for k in _TIMESTAMP_KEYS}
    if set(timestamps) - set(_TIMESTAMP_KEYS):
        raise ResponseConfigError(f"unknown timestamp keys {sorted(set(timestamps) - set(_TIMESTAMP_KEYS))}")
    if channel == "telegram" and ts["opened"] is not None:
        raise ResponseConfigError("Telegram has no read receipts; timestamps.opened must be None")

    event_rule = _check_event(channel, event)

    # 1. Which rule governs this attempt (before looking at answer content).
    wrong_farmer = answered_by is not None and answered_by != s["farmer_id"]
    if wrong_farmer:
        if event is not None:
            raise ResponseConfigError(
                f"answered_by {answered_by!r} differs from the survey farmer, which is "
                f"identity_mismatch; it cannot also be {event!r}"
            )
        rule: OutcomeRule | None = outcomes.failure_rule("identity_mismatch")
    else:
        rule = event_rule

    # 2. Interpret each question, in survey order.
    discarding = rule is not None and rule.status in _DISCARD_STATUSES
    record_items: list[dict[str, Any]] = []
    first_invalid_kind: str | None = None
    any_input = False
    for item_id, item in survey_items.items():
        obs = items.get(item_id, ItemObservation(shown=False))
        attempts = _check_observation(channel, item_id, obs)
        value: str | int | None = None
        if not obs.shown:
            result = "not_reached"
        elif obs.raw_input is None:
            result = "skipped"
        else:
            any_input = True
            value = interpret(s["survey_id"], item, obs.raw_input, obs.input_kind)
            if value is None:
                result = "invalid"
                first_invalid_kind = first_invalid_kind or obs.input_kind
            elif discarding:
                result = "discarded"
            else:
                result = "answered"
        record_items.append({
            "item_id": item_id,
            "item_type": item["type"],
            "result": result,
            "value": value,
            "raw_input": obs.raw_input,
            "input_kind": obs.input_kind if obs.raw_input is not None else None,
            "attempts": attempts,
        })

    if event in _NO_ANSWER_EVENTS and any_input:
        raise ResponseConfigError(f"{event!r} means nothing was answered, but input was given")

    # 3. Accepted answers and the follow-ups they actually carry.
    answers = {i["item_id"]: i["value"] for i in record_items if i["result"] == "answered"}
    reasons: list[str] = []
    for i in record_items:
        if i["result"] == "answered":
            r = follow_up_reason(survey_items[i["item_id"]], i["value"])
            if r and r not in reasons:
                reasons.append(r)

    # 4. Farmer input that matched no choice -> invalid_input under the rules.
    if rule is None and first_invalid_kind is not None:
        rule = outcomes.failure_rule(_FARMER_INVALID_CODE[first_invalid_kind])
        if channel not in rule.channels:
            raise ResponseConfigError(f"{rule.code!r} cannot happen on {channel}")

    # 5. Success: status follows from the accepted answers.
    sheet_outcome_override = None
    if rule is None or rule.code is None:  # no event, or a partial sheet case
        if rule is not None:  # sheet_closed_partway / sheet_interrupted
            sheet_outcome_override = rule.sheet_outcome
        if not answers:
            raise ResponseConfigError(
                "no accepted answers and no event explaining why; pass the event that "
                "ended the attempt (e.g. window_expired, sheet_dismissed)"
            )
        all_answered = all(i["result"] == "answered" for i in record_items)
        if reasons:
            status = "negative_outcome"  # only an ACCEPTED flagged answer gets here
        elif all_answered and sheet_outcome_override is None:
            status = "completed"
        else:
            status = "partial"
        base = outcomes.success_rule(status)
        rule = OutcomeRule(
            code=None, status=status,
            retry_decision=(rule or base).retry_decision,
            retry_after_minutes=(rule or base).retry_after_minutes,
            counts_toward_cap=(rule or base).counts_toward_cap,
            channels=base.channels,
            sheet_outcome=sheet_outcome_override,
        )

    # 6. Sheet outcome (app and web only).
    if channel in SHEET_CHANNELS:
        if rule.sheet_outcome is not None:
            sheet_outcome = rule.sheet_outcome
        elif rule.code in _SHEET_NEVER_OPENED:
            sheet_outcome = "never_opened"
        elif rule.code in _SHEET_DISMISSED:
            sheet_outcome = "dismissed"
        else:
            sheet_outcome = "finished"
    else:
        sheet_outcome = None

    # 7. What the FarmerChat answer store replied, if anything was sent.
    if rule.status == "duplicate":
        reply = {"http_status": 200, "outcome": "duplicate"}
    elif rule.code == "survey_replaced":
        reply = {"http_status": 404, "outcome": "unknown_flow"}  # flow was withdrawn
    elif rule.status in _DISCARD_STATUSES:
        reply = None  # dropped before it reaches FarmerChat
    elif answers and rule.retry_decision in ("none", "give_up"):
        reply = {"http_status": 201, "outcome": "accepted"}  # attempt finished; answers sent
    else:
        reply = None  # nothing to send yet (retrying, or nothing accepted)

    record: dict[str, Any] = {
        "response_key": response_key,
        "survey_id": s["survey_id"],
        "farmer_id": s["farmer_id"],
        "source_insight_ids": list(s["source_insight_ids"]),
        "channel": channel,
        "language": s["language"],
    }
    if question_type is not None:
        record["question_type"] = question_type
    record.update({
        "status": rule.status,
        "failure_code": rule.code,
        "sheet_outcome": sheet_outcome,
        "answers": answers,
        "items": record_items,
        "complete": all(i["result"] == "answered" for i in record_items),
        "delivery_attempt": delivery_attempt,
        "timestamps": ts,
        "recorded_at": recorded_at,
        "answered_by": answered_by,
        "raw_event": raw_event,
        "retry_decision": rule.retry_decision,
        "retry_after_minutes": rule.retry_after_minutes,
        "counts_toward_cap": rule.counts_toward_cap,
        "farmerchat_reply": reply,
        "needs_follow_up": bool(reasons),
        "follow_up_reasons": reasons,
    })

    errors = validate("response", record)
    if errors:
        raise ResponseConfigError("built record fails response.schema.json: " + "; ".join(errors[:5]))
    return record
