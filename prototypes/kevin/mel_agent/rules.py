"""Deterministic part of the agent: survey or not, send window, priority,
channel order and the scheduler hand-off.

Two policies exist so the evaluation can show a hill-climb:
- "baseline":   json/rules/rules.json and the brief, applied literally.
- "calibrated": changes found by comparing the baseline with the golden set
                (see CALIBRATION_NOTES). This is the default.
"""
import re
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone

from . import data

IST = timezone(timedelta(hours=5, minutes=30))
SURVEY_RESOLUTIONS = {k for k, v in data.rules()["survey_by_resolution"].items() if v["survey"]}
POLICIES = ("baseline", "calibrated")
DEFAULT_POLICY = "calibrated"

CALIBRATION_NOTES = [
    "R2: severity critical gets no survey; it needs a human call.",
    "R5: verification.needed false gets no survey.",
    "R7: no survey if the window opens after the crop's last calendar date.",
    "Windows ignore the action window: start = day lo at 09:00, end = day hi at 19:00.",
    "seasonal timing is days 30 to 45, not 21 to 45.",
    "same_day: opens 4 hours after the advice (not before 09:00) and stays open 4 hours; "
    "if that would open after 19:00, it opens at 09:00 the next day.",
    "Windows are cut at season end (31 March 19:00); no minimum width.",
]

REASONS = {
    "R1": ("junk_insight", "The insight is broken or off-topic, so there is no advice to check."),
    "R2": ("critical_needs_human_call", "Critical case. It needs a human call, not a survey."),
    "R3": ("nothing_to_verify", "Only general information was given, so there is no advice to check."),
    "R4": ("waiting_for_details", "No advice yet; the conversation is waiting for details."),
    "R5": ("no_check_needed", "The advice does not need a follow-up check."),
    "R6": ("window_after_season", "The send window would open after the rabi season ends."),
    "R7": ("crop_already_harvested", "The crop will be harvested before the survey could be sent."),
}


@dataclass
class Decision:
    insight_id: str
    farmer_id: str
    survey: bool
    rule: str
    reason_code: str | None = None
    reason: str | None = None
    send_window: dict | None = None
    priority: str | None = None
    channel_order: list = field(default_factory=list)

    def to_dict(self):
        return self.__dict__.copy()

    def no_survey_record(self):
        """Digital Green's no_survey JSON. Its schema only allows two reason codes,
        so other reasons are mapped to the closest one and kept in the reason text."""
        code = "needs_more_context" if self.reason_code == "waiting_for_details" else "generic_information"
        return {"insight_id": self.insight_id, "farmer_id": self.farmer_id, "decision": "no_survey",
                "reason_code": code, "reason": f"[{self.rule} {self.reason_code}] {self.reason}"[:300]}


def parse_ts(s):
    return datetime.fromisoformat(s).astimezone(IST)


def fmt_ts(dt):
    return dt.astimezone(IST).replace(microsecond=0).isoformat()


def _at(d, hhmm):
    h, m = map(int, hhmm.split(":"))
    return datetime.combine(d, time(h, m), IST)


def season_end():
    return _at(date.fromisoformat(data.rules()["window_rules"]["season_end"]), data.rules()["send_hours"]["to"])


def is_junk(ins):
    """Detects broken or off-topic insights without using the practice-only quality_flag."""
    if data.schema_errors("insight", {k: v for k, v in ins.items() if k != "quality_flag"}):
        return True
    if ins.get("decision_episode_type") == "casual":
        return True
    asset = ins.get("asset") or {}
    return asset.get("name") is None and ins.get("concern") is None


def send_window(ins, policy=DEFAULT_POLICY):
    """Returns (not_before, not_after) datetimes, or None if no timing is defined."""
    r = data.rules()
    created = parse_ts(ins["created_at"])
    timing = (ins.get("verification") or {}).get("timing") or "none"
    aw = ins.get("action_window_days")
    wr = r["window_rules"]
    send_from, send_to = r["send_hours"]["from"], r["send_hours"]["to"]

    if policy == "calibrated":
        if timing == "same_day":
            start = max(created + timedelta(hours=4), _at(created.date(), "09:00"))
            if start.date() != created.date() or start.time() > time(19, 0):
                start = _at(created.date() + timedelta(days=1), "09:00")
            end = start + timedelta(hours=4)
        else:
            if timing == "seasonal":
                lo, hi = 30, 45
            elif timing == "none":
                aw = wr["action_window_days_if_null"] if aw is None else aw
                lo, hi = aw + wr["none_start_after_action_window_days"], aw + wr["none_end_after_action_window_days"]
            else:
                lo, hi = r["send_window_days"][timing]
            start = _at(created.date() + timedelta(days=lo), "09:00")
            end = _at(created.date() + timedelta(days=hi), send_to)
        return start, min(end, season_end())

    # baseline: rules.json taken literally
    if timing == "none":
        aw = wr["action_window_days_if_null"] if aw is None else aw
        lo, hi = aw + wr["none_start_after_action_window_days"], aw + wr["none_end_after_action_window_days"]
    else:
        lo, hi = r["send_window_days"][timing]
    lo = max(lo, wr["earliest_start_day"])
    if wr["start_not_before_action_window_end"] and aw:
        lo = max(lo, aw)
    hi = max(hi, lo + wr["min_width_days"])
    start = _at(created.date() + timedelta(days=lo), wr["not_before_time"])
    end = _at(created.date() + timedelta(days=hi), wr["not_after_time"])
    return start, min(end, season_end())


def priority(ins):
    p = data.rules()["priority"]
    if (ins.get("resolution_type") in p["high_if_resolution"] or ins.get("severity") in p["high_if_severity"]
            or ins.get("behavioral_intent") in p["high_if_behavioral_intent"]):
        return "high"
    if ins.get("resolution_type") in p["low_if_resolution"]:
        return "low"
    return "normal"


def channel_order(ins, prio):
    r = data.rules()
    order = []
    for ch in (ins.get("preferred_channel"),
               r["channel_by_method"].get((ins.get("verification") or {}).get("method") or "none"),
               "whatsapp",
               "voice" if prio == "high" else None):
        if ch and ch not in order:
            order.append(ch)
    wait = r["wait_hours_by_priority"][prio]
    return [{"channel": c, "wait_hours": None if i == len(order) - 1 else wait} for i, c in enumerate(order)]


def decide(ins, policy=DEFAULT_POLICY):
    iid, fid = ins.get("insight_id", "?"), ins.get("farmer_id", "?")

    def skip(rule):
        code, why = REASONS[rule]
        return Decision(iid, fid, False, rule, code, why)

    cal = policy == "calibrated"
    if is_junk(ins):
        return skip("R1")
    if cal and ins.get("severity") == "critical":
        return skip("R2")
    res = ins.get("resolution_type")
    if res == "needs_more_context":
        return skip("R4")
    if res not in SURVEY_RESOLUTIONS:
        return skip("R3")
    if cal and not (ins.get("verification") or {}).get("needed"):
        return skip("R5")
    start, end = send_window(ins, policy)
    if start > season_end():
        return skip("R6")
    asset = ins.get("asset") or {}
    if cal and asset.get("category") == "crop":
        last = data.crop_last_day().get((asset.get("name") or "").lower())
        if last and start.date() > last:
            return skip("R7")
    prio = priority(ins)
    return Decision(iid, fid, True, "R8", send_window={"not_before": fmt_ts(start), "not_after": fmt_ts(end)},
                    priority=prio, channel_order=channel_order(ins, prio))


def survey_id_for(insight_ids):
    """Deterministic id from the first insight's number, so reruns give the same id."""
    digits = re.sub(r"\D", "", insight_ids[0]) or "0"
    return f"S-{int(digits):06d}"


def build_handoff(survey, decision, ins):
    r = data.rules()
    created = parse_ts(ins["created_at"]) + timedelta(minutes=30)
    expires = parse_ts(decision.send_window["not_after"]) + timedelta(days=r["expiry_days_after_window"])
    cap = r["frequency_cap"]
    flow = r["farmerchat_flow"]
    sid = survey["survey_id"]
    return {
        "handoff_id": "H-" + sid[2:],
        "created_at": fmt_ts(min(created, parse_ts(decision.send_window["not_before"]))),
        "survey": survey,
        "send_window": survey["send_window"],
        "send_hours": dict(r["send_hours"]),
        "channel_order": decision.channel_order,
        "frequency_cap": {"key": cap["key"].format(farmer_id=survey["farmer_id"]), "max_surveys": cap["max_surveys"],
                          "window_days": cap["window_days"], "exempt": decision.priority in cap["exempt_priority"]},
        "priority": decision.priority,
        "expires_at": fmt_ts(expires),
        "farmerchat_flow": {
            "org_id": flow["org_id"],
            "flow_key": flow["flow_key"].format(survey_id_lower=sid.lower().replace("-", "_")),
            "version": flow["version"],
            "campaign_id": str(uuid.uuid5(uuid.NAMESPACE_URL, flow["campaign_name"])),
            "flow_id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"{flow['campaign_name']}/{sid}")),
        },
    }
