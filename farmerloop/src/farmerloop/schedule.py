"""Deterministic scheduling: build a schema-valid schedule_handoff.

All logic comes from json/rules/rules.json. No LLM. Given an eligible insight
and its survey, we compute priority, the channel fallback order, the frequency
cap, the expiry, and the FarmerChat flow registration, then assemble a handoff
that validates against schedule_handoff.schema.json.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from . import ids
from .config import IST_OFFSET
from .decide import decide
from .models import Insight, Survey
from .timing import NOT_AFTER_TIME, SEASON_END, Window, compute_window
from .validate import validate

# India Standard Time (UTC+05:30); India has no DST.
_IST = timezone(timedelta(hours=5, minutes=30))

# rules.json priority.
_HIGH_RESOLUTIONS = {"escalate_to_expert"}
_HIGH_SEVERITY = {"high", "critical"}
_HIGH_INTENT = {"emergency"}
_LOW_RESOLUTIONS = {"plan_created", "do_not_act"}

# rules.json channel_by_method.
_METHOD_CHANNEL = {
    "push": "app",
    "whatsapp": "whatsapp",
    "ivr_callback": "voice",
    "repeat_photo": "app",
    "agent_followup": "voice",
    "none": None,
}

# rules.json wait_hours_by_priority.
_WAIT_HOURS = {"high": 6, "normal": 24, "low": 48}

# rules.json frequency_cap.
_CAP_MAX = 1
_CAP_WINDOW_DAYS = 7
_EXPIRY_DAYS_AFTER_WINDOW = 2

SEND_HOURS = {"from": "07:00", "to": "19:00"}


def compute_priority(insight: Insight) -> str:
    """high / normal / low per rules.json."""
    if (
        insight.resolution_type in _HIGH_RESOLUTIONS
        or insight.severity in _HIGH_SEVERITY
        or insight.behavioral_intent in _HIGH_INTENT
    ):
        return "high"
    if insight.resolution_type in _LOW_RESOLUTIONS:
        return "low"
    return "normal"


def compute_channel_order(insight: Insight, priority: str) -> list[dict[str, Any]]:
    """Ordered channel fallback list per rules.json channel_order_steps.

    1. preferred_channel
    2. the verification-method channel, if different
    3. WhatsApp, if not already listed
    4. Voice, only for high priority, if not already listed
    The last entry gets wait_hours=null; earlier ones get the priority wait.
    """
    order: list[str] = []

    def add(ch: str | None) -> None:
        if ch and ch not in order:
            order.append(ch)

    add(insight.preferred_channel)
    add(_METHOD_CHANNEL.get(insight.verification.method))
    add("whatsapp")
    if priority == "high":
        add("voice")

    wait = _WAIT_HOURS[priority]
    steps: list[dict[str, Any]] = []
    for i, ch in enumerate(order):
        last = i == len(order) - 1
        steps.append({"channel": ch, "wait_hours": None if last else wait})
    return steps


def _expiry_iso(window: Window) -> str:
    """Expiry = window end + 2 days, clamped to the season end, at 19:00 IST."""
    expiry_date = window.end + timedelta(days=_EXPIRY_DAYS_AFTER_WINDOW)
    if expiry_date > SEASON_END:
        expiry_date = SEASON_END
    return f"{expiry_date.isoformat()}T{NOT_AFTER_TIME}{IST_OFFSET}"


def _format_ist(dt: datetime) -> str:
    """Render a datetime as an IST timestamp string matching the schema.

    A timezone-aware datetime is CONVERTED to IST (not merely stamped with the
    offset); a naive datetime is assumed to already be IST.
    """
    if dt.tzinfo is not None:
        dt = dt.astimezone(_IST)
    else:
        dt = dt.replace(tzinfo=_IST)
    # Preserve fractional seconds so a just-closed window cannot be reopened
    # by rounding the handoff creation timestamp down to the boundary.
    return dt.isoformat()


def build_handoff(
    insight: Insight,
    survey: Survey,
    window: Window,
    *,
    created_at: str | datetime,
) -> dict[str, Any]:
    """Assemble a schema-valid schedule_handoff dict.

    ``created_at`` is the REAL handoff creation time (production: a tz-aware
    "now"; tests/demo: an explicit reference). A handoff created AT OR AFTER its
    expiry, or after its send window closes, is rejected. Creation before or
    during an otherwise-valid send window is allowed; sending must occur
    inside the window.
    """
    # Do not trust a caller to have run the input and eligibility gates.
    # exclude_unset preserves omission of the optional practice quality_flag;
    # required nullable fields must still be present in the source model.
    errors = validate("insight", insight.model_dump(mode="json", exclude_unset=True))
    if errors:
        raise ValueError("Invalid insight for scheduling: " + "; ".join(errors[:3]))
    decision = decide(insight)
    if not decision.survey:
        raise ValueError("Insight is not eligible: " + decision.internal_reason_code)
    expected_window = compute_window(
        insight.created_at, insight.verification.timing, insight.action_window_days
    )
    if expected_window is None:
        raise ValueError("No feasible send window under the documented timing rules")
    if window != expected_window:
        raise ValueError("Supplied window differs from the insight's computed send window")

    # Validate at the handoff boundary, including callers that bypass generators.
    from .quality import require_quality
    require_quality(insight, survey)
    if survey.send_window.dump() != {"not_before": window.not_before_iso(), "not_after": window.not_after_iso()}:
        raise ValueError("Survey and handoff windows differ")
    priority = compute_priority(insight)
    sid = survey.survey_id
    cap_exempt = priority == "high"

    if isinstance(created_at, str):
        created_dt = datetime.fromisoformat(created_at)
        if created_dt.tzinfo is None:
            raise ValueError("String created_at must include a timezone offset")
    else:
        created_dt = created_at
    created_str = _format_ist(created_dt)
    expires_str = _expiry_iso(window)

    # Chronology guard: never create a handoff that is already expired.
    if datetime.fromisoformat(created_str) >= datetime.fromisoformat(expires_str):
        raise ValueError(
            f"handoff created_at {created_str} is at/after expires_at {expires_str}"
        )
    if datetime.fromisoformat(created_str) > datetime.fromisoformat(window.not_after_iso()):
        raise ValueError("Cannot schedule a survey after its send window has closed")

    handoff = {
        "handoff_id": ids.handoff_id(sid),
        "created_at": created_str,
        "survey": survey.dump(),
        "send_window": survey.send_window.dump(),
        "send_hours": dict(SEND_HOURS),
        "channel_order": compute_channel_order(insight, priority),
        "frequency_cap": {
            "key": f"mel:farmer:{survey.farmer_id}",
            "max_surveys": _CAP_MAX,
            "window_days": _CAP_WINDOW_DAYS,
            "exempt": cap_exempt,
        },
        "priority": priority,
        "expires_at": expires_str,
        "farmerchat_flow": {
            "org_id": ids.ORG_ID,
            "flow_key": ids.flow_key(sid),
            "version": 1,
            "campaign_id": ids.campaign_id(),
            "flow_id": ids.flow_id(sid),
        },
    }
    errors = validate("schedule_handoff", handoff)
    if errors:
        raise ValueError("Invalid schedule handoff: " + "; ".join(errors[:3]))
    return handoff
