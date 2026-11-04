"""Scheduler hand-off construction: priority, channel order, cap, expiry, flow ids.

Everything is derived from rules.json plus the insight and the survey. Ids are
deterministic so that re-running the pipeline produces identical documents.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from datetime import timedelta
from typing import Any

from mel_agent.data.pack import Rules
from mel_agent.rules.timing import SendWindow
from mel_agent.time_utils import format_ist, ist_datetime, parse_ist

CHANNELS = ("app", "web", "whatsapp", "telegram", "voice")
# Namespace for our uuid5 ids. The pack's example ids are v5 UUIDs under an unpublished namespace.
_MEL_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "https://farmerchat.digitalgreen.org/mel/")
_PACK_ID = re.compile(r"^I-(\d{6})$")


def survey_id_for(insight_id: str) -> str:
    """Deterministic survey id for one insight (survey.schema.json: ^S-[0-9]{5,10}$).

    Pack-style ids map readably (I-004512 -> S-004512). Any other id is hashed over
    its FULL text into ten digits, so "X-123456" and "I-123456" never share an id.
    The store additionally enforces uniqueness of survey ids across insights."""
    if not isinstance(insight_id, str) or not insight_id:
        raise ValueError("insight_id must be a non-empty string")
    m = _PACK_ID.match(insight_id)
    if m:
        return f"S-{m.group(1)}"
    digest = hashlib.sha256(insight_id.encode("utf-8")).digest()
    return f"S-{int.from_bytes(digest[:8], 'big') % 10**10:010d}"


def handoff_id_for(survey_id: str) -> str:
    return "H-" + survey_id[2:]


def priority_for(insight: dict[str, Any], rules: Rules) -> str:
    p = rules.priority
    if insight.get("resolution_type") in p.get("high_if_resolution", []):
        return "high"
    if insight.get("severity") in p.get("high_if_severity", []):
        return "high"
    if insight.get("behavioral_intent") in p.get("high_if_behavioral_intent", []):
        return "high"
    if insight.get("resolution_type") in p.get("low_if_resolution", []):
        return "low"
    return p.get("otherwise", "normal")


def channel_order_for(insight: dict[str, Any], priority: str, rules: Rules) -> list[dict[str, Any]]:
    """rules.json channel_order_steps: preferred, then the verification method's channel,
    then WhatsApp, then voice (high priority only). Last entry waits forever (null)."""
    order: list[str] = []

    def add(ch: str | None) -> None:
        if ch and ch in CHANNELS and ch not in order:
            order.append(ch)

    add(insight.get("preferred_channel"))
    method = (insight.get("verification") or {}).get("method") or "none"
    add(rules.channel_by_method.get(method))
    add("whatsapp")
    if priority == "high":
        add("voice")
    wait = int(rules.wait_hours_by_priority[priority])
    return [{"channel": ch, "wait_hours": (wait if i < len(order) - 1 else None)} for i, ch in enumerate(order)]


def frequency_cap_for(farmer_id: str, priority: str, rules: Rules) -> dict[str, Any]:
    cap = rules.frequency_cap
    return {
        "key": cap["key"].replace("{farmer_id}", farmer_id),
        "max_surveys": int(cap["max_surveys"]),
        "window_days": int(cap["window_days"]),
        "exempt": priority in cap.get("exempt_priority", []),
    }


def farmerchat_flow_for(survey_id: str, rules: Rules) -> dict[str, Any]:
    flow = rules.farmerchat_flow
    flow_key = flow["flow_key"].replace("{survey_id_lower}", survey_id.lower().replace("-", "_"))
    campaign = flow["campaign_name"]
    return {
        "org_id": flow["org_id"],
        "flow_key": flow_key,
        "version": int(flow["version"]),
        "campaign_id": str(uuid.uuid5(_MEL_NAMESPACE, f"campaign/{campaign}")),
        "flow_id": str(uuid.uuid5(_MEL_NAMESPACE, f"flow/{campaign}/{flow_key}/v{flow['version']}")),
    }


def handoff_created_at(insight: dict[str, Any]) -> str:
    """The worked scenarios hand off at 23:00 IST on the insight's day (a nightly batch)."""
    day = parse_ist(insight["created_at"]).date()
    return format_ist(ist_datetime(day, "23:00"))


def build_handoff(insight: dict[str, Any], survey: dict[str, Any], window: SendWindow, rules: Rules) -> dict[str, Any]:
    priority = priority_for(insight, rules)
    expires = window.not_after + timedelta(days=rules.expiry_days_after_window)
    return {
        "handoff_id": handoff_id_for(survey["survey_id"]),
        "created_at": handoff_created_at(insight),
        "survey": survey,
        "send_window": window.to_contract(),
        "send_hours": {"from": rules.send_hours["from"], "to": rules.send_hours["to"]},
        "channel_order": channel_order_for(insight, priority, rules),
        "frequency_cap": frequency_cap_for(survey["farmer_id"], priority, rules),
        "priority": priority,
        "expires_at": format_ist(expires),
        "farmerchat_flow": farmerchat_flow_for(survey["survey_id"], rules),
    }
