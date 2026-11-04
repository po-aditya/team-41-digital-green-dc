"""Deterministic simulation of how a farmer reacts to one delivery attempt.

Produces ``response`` records (response.schema.json) using the statuses and
codes in outcome_codes.json. Nothing here talks to a real channel. Outcomes are
drawn from a seeded hash of (survey_id, channel, attempt) so a replay gives the
same answers; a ScriptedSimulator forces specific outcomes for demos and tests.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from mel_agent.data.pack import OutcomeCodes
from mel_agent.time_utils import format_ist

INPUT_KIND = {"app": "sheet_tap", "web": "sheet_tap", "whatsapp": "button_reply", "telegram": "callback_data", "voice": "keypad"}
SUCCESS_STATUSES = ("completed", "partial", "negative_outcome")

# Relative frequency of simulated reactions per channel. Synthetic, for demonstration only.
_WEIGHTS: dict[str, list[tuple[str, int]]] = {
    "app": [("completed", 45), ("partial", 10), ("sheet_dismissed", 10), ("push_not_opened", 15), ("push_token_invalid", 5), ("silent", 15)],
    "web": [("completed", 40), ("partial", 10), ("sheet_dismissed", 10), ("client_cannot_render", 5), ("silent", 35)],
    "whatsapp": [("completed", 50), ("partial", 10), ("farmer_declined", 8), ("wa_undelivered", 7), ("free_text_instead_of_choice", 10), ("silent", 15)],
    "telegram": [("completed", 40), ("partial", 10), ("farmer_declined", 8), ("tg_bot_blocked", 12), ("free_text_instead_of_choice", 10), ("silent", 20)],
    "voice": [("completed", 40), ("partial", 10), ("voice_no_answer", 20), ("voice_busy", 10), ("farmer_declined", 8), ("keypad_out_of_range", 7), ("silent", 5)],
}


@dataclass
class Reaction:
    """What the simulated farmer/channel does. ``record`` is None when nothing ever comes back."""

    outcome: str  # a success status, a failure code, or "silent"
    delay_minutes: int
    record: dict[str, Any] | None


def _seeded(seed: int, *parts: str) -> int:
    h = hashlib.sha256(("|".join(str(p) for p in parts) + f"|{seed}").encode()).hexdigest()
    return int(h[:12], 16)


def _pick(weights: list[tuple[str, int]], roll: int) -> str:
    total = sum(w for _, w in weights)
    r = roll % total
    for name, w in weights:
        if r < w:
            return name
        r -= w
    return weights[-1][0]


def _answer_for(item: dict[str, Any], roll: int) -> tuple[Any, str | None]:
    """Pick one option deterministically. Returns (value, follow_up_reason)."""
    if item["type"] == "survey-scale":
        lo, hi = int(item["scale_min"]), int(item["scale_max"])
        v = lo + roll % (hi - lo + 1)
        reason = item.get("follow_up_reason") if "follow_up_at_or_below" in item and v <= int(item["follow_up_at_or_below"]) else None
        return v, reason
    opts = item["options"]
    # Bias toward the first option (usually the "good" answer) while keeping follow-ups reachable.
    idx = roll % (len(opts) + 2)
    o = opts[idx if idx < len(opts) else 0]
    return o["value"], o.get("follow_up")


class Simulator:
    def __init__(self, outcome_codes: OutcomeCodes, seed: int) -> None:
        self.codes = outcome_codes
        self.seed = seed

    def choose_outcome(self, survey: dict[str, Any], channel: str, attempt: int) -> str:
        return _pick(_WEIGHTS[channel], _seeded(self.seed, survey["survey_id"], channel, attempt, "outcome"))

    def react(self, survey: dict[str, Any], channel: str, attempt: int, sent_at: datetime, outcome: str | None = None) -> Reaction:
        outcome = outcome or self.choose_outcome(survey, channel, attempt)
        if outcome == "silent":
            return Reaction("silent", 0, None)
        roll = _seeded(self.seed, survey["survey_id"], channel, attempt, "detail")
        if outcome in SUCCESS_STATUSES or outcome in ("sheet_closed_partway", "sheet_interrupted"):
            delay = 20 + roll % 300
            record = self._success_record(survey, channel, attempt, sent_at, outcome, roll)
        else:
            spec = self.codes.failure(outcome)
            if channel not in spec["channels"]:
                raise ValueError(f"outcome {outcome} is not defined for channel {channel}")
            delay = 2 if spec["status"] == "delivery_failed" else 30 + roll % 600
            record = self._failure_record(survey, channel, attempt, sent_at, outcome, spec, delay)
        return Reaction(outcome, delay, record)

    # ---------- record builders ----------

    def _base(self, survey: dict[str, Any], channel: str, attempt: int, key_suffix: str) -> dict[str, Any]:
        return {
            "response_key": f"rk-{survey['survey_id']}-{channel}-{attempt}-{key_suffix}"[:64],
            "survey_id": survey["survey_id"], "farmer_id": survey["farmer_id"],
            "source_insight_ids": list(survey["source_insight_ids"]), "channel": channel, "language": survey["language"],
        }

    def _success_record(self, survey, channel, attempt, sent_at, outcome, roll) -> dict[str, Any]:
        items_out, answers, reasons = [], {}, set()
        n_items = len(survey["items"])
        answered_count = n_items if outcome in ("completed", "negative_outcome") else max(1, (roll // 7) % n_items) if n_items > 1 else 1
        if outcome in ("sheet_closed_partway", "sheet_interrupted", "partial") and n_items > 1:
            answered_count = min(answered_count, n_items - 1)
        for idx, item in enumerate(survey["items"]):
            if idx < answered_count:
                value, reason = _answer_for(item, (roll >> (idx * 4)) + idx)
                if reason:
                    reasons.add(reason)
                answers[item["item_id"]] = value
                items_out.append({"item_id": item["item_id"], "item_type": item["type"], "result": "answered", "value": value,
                                  "raw_input": str(value) if channel in ("app", "web") else f"{survey['survey_id']}|{item['item_id']}|{value}",
                                  "input_kind": INPUT_KIND[channel], "attempts": 1})
            else:
                result = "skipped" if outcome in ("partial", "sheet_closed_partway") else "not_reached"
                items_out.append({"item_id": item["item_id"], "item_type": item["type"], "result": result, "value": None,
                                  "raw_input": None, "input_kind": None, "attempts": 1 if result == "skipped" else 0})
        complete = answered_count == n_items
        if reasons:
            status = "negative_outcome"
        elif complete:
            status = "completed"
        else:
            status = "partial"
        sheet_outcome = None
        if channel in ("app", "web"):
            sheet_outcome = {"sheet_closed_partway": "closed_partway", "sheet_interrupted": "interrupted"}.get(outcome, "finished" if complete else "closed_partway")
        opened = sent_at + timedelta(minutes=15)
        answered = opened + timedelta(minutes=5)
        rec = self._base(survey, channel, attempt, status)
        rec.update({
            "status": status, "failure_code": None, "sheet_outcome": sheet_outcome, "answers": answers, "items": items_out,
            "complete": complete, "delivery_attempt": attempt,
            "timestamps": {"sent": format_ist(sent_at), "delivered": format_ist(sent_at + timedelta(minutes=1)),
                           "opened": None if channel == "telegram" else format_ist(opened), "answered": format_ist(answered)},
            "recorded_at": format_ist(answered), "answered_by": survey["farmer_id"], "raw_event": None,
            "retry_decision": "none", "retry_after_minutes": None, "counts_toward_cap": True,
            "farmerchat_reply": {"http_status": 201, "outcome": "accepted"},
            "needs_follow_up": bool(reasons), "follow_up_reasons": sorted(reasons),
        })
        return rec

    def _failure_record(self, survey, channel, attempt, sent_at, code, spec, delay) -> dict[str, Any]:
        status = spec["status"]
        delivered = status not in ("delivery_failed",) or code in ("voice_call_dropped",)
        reached = status in ("declined", "invalid_input", "expired") and code not in ("push_not_opened",)
        items_out = []
        for item in survey["items"]:
            result = "skipped" if reached else "not_reached"
            if code in ("free_text_instead_of_choice", "keypad_out_of_range", "speech_not_understood") and item is survey["items"][0]:
                result = "invalid"
            items_out.append({"item_id": item["item_id"], "item_type": item["type"], "result": result, "value": None,
                              "raw_input": ("free text" if code == "free_text_instead_of_choice" else "9" if code == "keypad_out_of_range" else None) if result == "invalid" else None,
                              "input_kind": ("free_text" if code == "free_text_instead_of_choice" else "keypad" if code == "keypad_out_of_range" else "speech" if code == "speech_not_understood" else None) if result == "invalid" else None,
                              "attempts": 2 if result == "invalid" else (1 if reached else 0)})
        sheet_outcome = None
        if channel in ("app", "web"):
            sheet_outcome = {"sheet_dismissed": "dismissed", "push_not_opened": "never_opened", "client_cannot_render": "never_opened",
                             "push_token_invalid": "never_opened", "survey_closed": "never_opened", "survey_replaced": "never_opened",
                             "farmer_opted_out": "finished", "window_expired": "never_opened", "duplicate_answer": "finished",
                             "identity_mismatch": "finished"}.get(code, "never_opened")
        at = sent_at + timedelta(minutes=delay)
        rec = self._base(survey, channel, attempt, code)
        rec.update({
            "status": status, "failure_code": code, "sheet_outcome": sheet_outcome, "answers": {}, "items": items_out,
            "complete": False, "delivery_attempt": attempt,
            "timestamps": {"sent": format_ist(sent_at), "delivered": format_ist(sent_at + timedelta(minutes=1)) if delivered else None,
                           "opened": format_ist(at) if reached and channel != "telegram" else None, "answered": None},
            "recorded_at": format_ist(at), "answered_by": survey["farmer_id"] if reached else None,
            "raw_event": {"farmer_declined": "declined", "farmer_opted_out": "STOP", "wa_undelivered": "message undeliverable",
                          "tg_bot_blocked": "bot blocked by user", "voice_no_answer": "no answer after 3 calls", "voice_busy": "line busy",
                          "voice_call_dropped": "call dropped", "push_token_invalid": "push token invalid", "client_cannot_render": "unsupported client",
                          "wa_session_window_closed": "session window closed", "sheet_dismissed": "sheet dismissed", "push_not_opened": "push not opened",
                          "window_expired": "window expired"}.get(code),
            "retry_decision": spec["retry_decision"], "retry_after_minutes": spec["retry_after_minutes"],
            "counts_toward_cap": bool(spec["counts_toward_cap"]), "farmerchat_reply": None, "needs_follow_up": False, "follow_up_reasons": [],
        })
        return rec


class ScriptedSimulator(Simulator):
    """Forces outcomes: script maps (survey_id, channel, attempt) or survey_id -> list of outcomes."""

    def __init__(self, outcome_codes: OutcomeCodes, seed: int, script: dict[Any, Any]) -> None:
        super().__init__(outcome_codes, seed)
        self.script = script

    def choose_outcome(self, survey: dict[str, Any], channel: str, attempt: int) -> str:
        key = (survey["survey_id"], channel, attempt)
        if key in self.script:
            return self.script[key]
        seq = self.script.get(survey["survey_id"])
        if isinstance(seq, list) and seq:
            return seq.pop(0)
        if isinstance(seq, str):
            return seq
        return super().choose_outcome(survey, channel, attempt)
