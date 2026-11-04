"""Scheduling / handoff tests, including chronology and timezone handling."""

from datetime import datetime, timedelta, timezone

import pytest

from farmerloop.generate_contextual import ContextualSurveyGenerator
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
        "query_summary": "Farmer asks about insects on wheat.", "advice_summary": "Advised to spray a recommended insecticide as per the label.", "resolution_type": "direct_action",
        "action_window_days": 2,
        "verification": {"needed": True, "timing": "two_to_five_days", "method": "push"},
        "preferred_channel": "app", "quality_flag": "clean",
    }
    base.update(over)
    return Insight.model_validate(base)


def _survey_window(ins):
    w = compute_window(ins.created_at, ins.verification.timing, ins.action_window_days)
    s = ContextualSurveyGenerator().generate(ins, w)
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


@pytest.mark.parametrize("change,reason", [
    ({"quality_flag": "junk"}, "junk_insight"),
    ({"severity": "critical"}, "critical_needs_human_call"),
    ({"verification": {"needed": False, "timing": "two_to_five_days", "method": "push"}}, "no_check_needed"),
    ({"resolution_type": "generic_information"}, "nothing_to_verify"),
    ({"resolution_type": "needs_more_context"}, "waiting_for_details"),
    ({"created_at": "2027-03-31T09:00:00+05:30"}, "window_after_season"),
])
def test_direct_handoff_call_cannot_bypass_eligibility(change, reason):
    ins = _insight()
    survey, window = _survey_window(ins)
    changed = _insight(**change)
    with pytest.raises(ValueError, match=reason):
        build_handoff(changed, survey, window, created_at="2026-11-05T19:00:00+05:30")


@pytest.mark.parametrize("change", [
    {"created_at": "2026-11-05T23:00:00Z"},
    {"action_window_days": -1},
    {"verification": {"needed": True, "timing": "misspelled", "method": "push"}},
])
def test_permissive_model_cannot_bypass_input_schema(change):
    ins = _insight()
    survey, window = _survey_window(ins)
    with pytest.raises(ValueError, match="Invalid insight"):
        build_handoff(_insight(**change), survey, window, created_at="2026-11-05T19:00:00+05:30")


@pytest.mark.parametrize("start,end", [
    ("2026-11-05", "2026-11-07"),  # same day / before action deadline
    ("2026-11-07", "2026-11-08"),  # too narrow
    ("2026-11-07", "2027-04-02"),  # beyond season
    ("2026-11-08", "2026-11-11"),  # legal-shaped, but not the computed window
])
def test_matching_survey_and_window_cannot_bypass_timing(start, end):
    from datetime import date
    from farmerloop.timing import Window
    ins = _insight()
    survey, _ = _survey_window(ins)
    window = Window(date.fromisoformat(start), date.fromisoformat(end))
    survey.send_window.not_before = window.not_before_iso()
    survey.send_window.not_after = window.not_after_iso()
    with pytest.raises(ValueError, match="computed send window"):
        build_handoff(ins, survey, window, created_at="2026-11-05T19:00:00+05:30")


def test_no_handoff_when_eligible_but_season_has_no_room_for_minimum_width():
    from farmerloop.decide import decide
    ins = _insight()
    survey, window = _survey_window(ins)
    late = _insight(created_at="2027-03-28T18:05:00+05:30", action_window_days=3,
                    verification={"needed": True, "timing": "three_to_ten_days", "method": "push"})
    assert decide(late).survey  # Eligibility is not a guarantee of schedulability.
    with pytest.raises(ValueError, match="No feasible send window"):
        build_handoff(late, survey, window, created_at="2027-03-28T19:00:00+05:30")


@pytest.mark.parametrize("delay", [timedelta(seconds=1), timedelta(microseconds=1)])
def test_closed_window_cannot_be_scheduled_during_late_answer_grace_period(delay):
    ins = _insight()
    survey, window = _survey_window(ins)
    closed = datetime.fromisoformat(window.not_after_iso()) + delay
    with pytest.raises(ValueError, match="send window has closed"):
        build_handoff(ins, survey, window, created_at=closed)


def test_string_creation_time_is_converted_to_ist_and_naive_string_rejected():
    ins = _insight()
    survey, window = _survey_window(ins)
    h = build_handoff(ins, survey, window, created_at="2026-11-06T20:00:00Z")
    assert h["created_at"] == "2026-11-07T01:30:00+05:30"
    assert not validate("schedule_handoff", h)
    with pytest.raises(ValueError, match="timezone offset"):
        build_handoff(ins, survey, window, created_at="2026-11-06T20:00:00")


def test_valid_source_without_optional_practice_flag_can_be_scheduled():
    raw = _insight().raw
    raw.pop("quality_flag")
    ins = Insight.model_validate(raw)
    survey, window = _survey_window(ins)
    assert build_handoff(ins, survey, window, created_at="2026-11-06T19:00:00+05:30")
