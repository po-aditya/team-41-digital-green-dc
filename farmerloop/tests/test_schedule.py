"""Scheduling / handoff tests, including chronology and timezone handling."""

from datetime import datetime, timedelta, timezone

import pytest

from farmerloop.generate_fake import FakeSurveyGenerator
from farmerloop.models import Insight
from farmerloop.schedule import build_handoff, compute_priority, _format_ist
from farmerloop.timing import compute_window
from farmerloop.validate import validate

UTC = timezone.utc
IST = timezone(timedelta(hours=5, minutes=30))


def _insight(**over):
    base = {
        "insight_id": "I-000263", "farmer_id": "F-000016", "conversation_id": "C-1",
        "created_at": "2026-11-05T09:00:00+05:30", "conversation_language": "hi-IN",
        "location": {"country": "IN", "state": "Bihar", "district": "Patna"},
        "asset": {"name": "wheat", "category": "crop", "growth_stage": None},
        "concern": "pest_disease", "behavioral_intent": "procedural_guidance",
        "decision_episode_type": "decision", "severity": "medium",
        "query_summary": "q", "advice_summary": "a", "resolution_type": "direct_action",
        "action_window_days": 2,
        "verification": {"needed": True, "timing": "two_to_five_days", "method": "push"},
        "preferred_channel": "app", "quality_flag": "clean",
    }
    base.update(over)
    return Insight.model_validate(base)


def _survey_window(ins):
    w = compute_window(ins.created_at, ins.verification.timing, ins.action_window_days)
    s = FakeSurveyGenerator().generate(ins, w)
    return s, w


def test_handoff_is_schema_valid():
    ins = _insight()
    s, w = _survey_window(ins)
    created = datetime.combine(w.start, datetime.min.time()).replace(tzinfo=IST)
    h = build_handoff(ins, s, w, created_at=created - timedelta(days=1))
    assert validate("schedule_handoff", h) == []


def test_priority_rules():
    assert compute_priority(_insight(resolution_type="escalate_to_expert")) == "high"
    assert compute_priority(_insight(severity="critical")) == "high"
    assert compute_priority(_insight(behavioral_intent="emergency")) == "high"
    assert compute_priority(_insight(resolution_type="plan_created")) == "low"
    assert compute_priority(_insight(resolution_type="do_not_act")) == "low"
    assert compute_priority(_insight(resolution_type="direct_action")) == "normal"


def test_format_ist_converts_utc_to_ist():
    # 2026-11-13T17:30:00Z == 2026-11-13T23:00:00+05:30.
    dt = datetime(2026, 11, 13, 17, 30, 0, tzinfo=UTC)
    assert _format_ist(dt) == "2026-11-13T23:00:00+05:30"


def test_format_ist_naive_assumed_ist():
    dt = datetime(2026, 11, 13, 23, 0, 0)
    assert _format_ist(dt) == "2026-11-13T23:00:00+05:30"


def test_created_during_active_window_is_allowed():
    ins = _insight()
    s, w = _survey_window(ins)
    # created at the moment the window opens (inside window, before expiry).
    created = s.send_window.not_before
    h = build_handoff(ins, s, w, created_at=created)
    assert h["created_at"] == created
    assert validate("schedule_handoff", h) == []


def test_created_at_or_after_expiry_rejected():
    ins = _insight()
    s, w = _survey_window(ins)
    expiry = h_expiry = None
    # Build once to read the expiry, then attempt a creation at that instant.
    good = build_handoff(ins, s, w, created_at=s.send_window.not_before)
    expiry = good["expires_at"]
    with pytest.raises(ValueError):
        build_handoff(ins, s, w, created_at=expiry)  # exactly at expiry
    # Also strictly after expiry.
    after = (datetime.fromisoformat(expiry) + timedelta(days=1))
    with pytest.raises(ValueError):
        build_handoff(ins, s, w, created_at=after)
