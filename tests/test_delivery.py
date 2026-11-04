"""Simulated delivery: answer records, broadcaster state machine, cap, fallback, retry, expiry, idempotency."""

from __future__ import annotations

import json

import pytest

from mel_agent.delivery.bottom_sheet import render_bottom_sheet
from mel_agent.delivery.clock import SimulatedClock
from mel_agent.delivery.simulator import ScriptedSimulator, Simulator
from mel_agent.rules.scheduling import survey_id_for
from mel_agent.time_utils import parse_ist


@pytest.fixture
def survey(load_example):
    return load_example("scenarios/1-mustard-aphid-spray/survey.en-IN.json")  # includes follow_up options


@pytest.fixture
def scale_survey(load_example):
    return load_example("scenarios/3-potato-blight-wait/survey.en-IN.json")  # includes a survey-scale item


def test_every_simulated_outcome_is_schema_valid(outcome_codes, registry, survey, scale_survey):
    sim = Simulator(outcome_codes, seed=1)
    sent = parse_ist("2026-12-06T08:00:00+05:30")
    for s in (survey, scale_survey):
        for channel in ("app", "web", "whatsapp", "telegram", "voice"):
            outcomes = ["completed", "partial", "negative_outcome"] + outcome_codes.failures_for_channel(channel)
            if channel in ("app", "web"):
                outcomes += ["sheet_closed_partway", "sheet_interrupted"]
            for outcome in outcomes:
                reaction = sim.react(s, channel, 1, sent, outcome=outcome)
                errors = registry.errors("response", reaction.record)
                assert not errors, (channel, outcome, [(e.path, e.validator) for e in errors[:3]])
                rec = reaction.record
                assert rec["channel"] == channel and rec["survey_id"] == s["survey_id"]
                if rec["status"] in ("completed", "partial", "negative_outcome"):
                    assert rec["failure_code"] is None and rec["farmerchat_reply"]["outcome"] == "accepted"
                    assert rec["needs_follow_up"] == bool(rec["follow_up_reasons"])
                    assert (rec["status"] == "negative_outcome") == rec["needs_follow_up"]
                else:
                    assert rec["failure_code"] == outcome and rec["answers"] == {}
                    spec = outcome_codes.failure(outcome)
                    assert rec["status"] == spec["status"] and rec["retry_decision"] == spec["retry_decision"]
                    assert rec["counts_toward_cap"] == spec["counts_toward_cap"]
                if channel in ("whatsapp", "telegram", "voice"):
                    assert rec["sheet_outcome"] is None
                if channel == "telegram":
                    assert rec["timestamps"]["opened"] is None


def test_simulator_is_deterministic_and_seeded(outcome_codes, survey):
    sent = parse_ist("2026-12-06T08:00:00+05:30")
    a = Simulator(outcome_codes, 7).react(survey, "whatsapp", 1, sent)
    b = Simulator(outcome_codes, 7).react(survey, "whatsapp", 1, sent)
    assert a.outcome == b.outcome and a.record == b.record
    outcomes = {Simulator(outcome_codes, seed).choose_outcome(survey, "whatsapp", 1) for seed in range(40)}
    assert len(outcomes) > 1


def test_silent_reaction_and_invalid_channel_outcome(outcome_codes, survey):
    sim = Simulator(outcome_codes, 1)
    sent = parse_ist("2026-12-06T08:00:00+05:30")
    assert sim.react(survey, "app", 1, sent, outcome="silent").record is None
    with pytest.raises(ValueError):
        sim.react(survey, "voice", 1, sent, outcome="wa_undelivered")


def test_bottom_sheet_renders_valid_for_app_and_web(registry, survey, scale_survey, load_example):
    for s in (survey, scale_survey, load_example("scenarios/1-mustard-aphid-spray/survey.hi-IN.json")):
        for channel in ("app", "web"):
            sheet = render_bottom_sheet(s, channel)
            assert not registry.errors("bottom_sheet", sheet), (s["survey_id"], channel)
            assert sheet["presentation"]["steps_total"] == len(s["items"])
    with pytest.raises(ValueError):
        render_bottom_sheet(survey, "voice")


# ---------- broadcaster over the pipeline ----------

def _schedule_one(pipeline, insight_id, script=None):
    """Schedule one insight; merge any outcome script into the pipeline's scripted simulator."""
    now = "2026-11-01T00:00:00+05:30"
    sid = survey_id_for(insight_id)
    if script is not None:
        if isinstance(pipeline.simulator, ScriptedSimulator):
            pipeline.simulator.script.update(script)
        else:
            pipeline.simulator = ScriptedSimulator(pipeline.outcome_codes, 1, dict(script))
    out = pipeline.process_insight(insight_id, now)
    assert out.get("generation", {}).get("status") == "scheduled", out
    return pipeline.store.get_handoff_for_survey(sid)


def _find(store, **props):
    """First schema-valid insight matching the given top-level properties."""
    for row in store.iter_insights(only_valid=True):
        obj = json.loads(row["raw_json"])
        v = obj.get("verification") or {}
        if not v.get("needed") or obj.get("severity") == "critical":
            continue
        if all((obj.get(k) == val) for k, val in props.items()):
            return obj["insight_id"], obj
    raise AssertionError("no insight matches")


def test_nothing_is_sent_before_window_or_outside_send_hours(pipeline):
    iid, obj = _find(pipeline.store, resolution_type="direct_action", preferred_channel="whatsapp")
    h = _schedule_one(pipeline, iid, {survey_id_for(iid): ["completed"]})
    b = pipeline.broadcaster()
    pipeline.clock.set(parse_ist(h["not_before"]).replace(hour=6, minute=0))  # same day, before 07:00
    pipeline.clock.advance(days=-1)
    assert b.tick().sent == 0
    pipeline.clock.set(parse_ist(h["not_before"]).replace(hour=5, minute=0))
    assert b.tick().sent == 0
    pipeline.clock.set(h["not_before"])
    assert b.tick().sent == 1
    assert pipeline.store.get_handoff(h["handoff_id"])["state"] == "in_progress"


def test_answer_flow_and_cap_counting(pipeline):
    iid, obj = _find(pipeline.store, resolution_type="direct_action", preferred_channel="app")
    h = _schedule_one(pipeline, iid, {survey_id_for(iid): ["completed"]})
    pipeline.clock.set(h["not_before"])
    b = pipeline.broadcaster()
    b.tick()
    pipeline.clock.advance(hours=6)
    rep = b.tick()
    assert rep.answered == 1
    row = pipeline.store.get_handoff(h["handoff_id"])
    assert row["state"] == "answered" and row["counted_at"] is not None
    resp = pipeline.store.list_responses(survey_id=h["survey_id"]).items
    assert len(resp) == 1 and resp[0]["status"] == "completed"


def test_fallback_to_next_channel_and_retry_same_channel(pipeline):
    iid, obj = _find(pipeline.store, resolution_type="escalate_to_expert", preferred_channel="voice")
    sid = survey_id_for(iid)
    h = _schedule_one(pipeline, iid, {sid: ["voice_busy", "voice_no_answer", "completed"]})
    order = [c["channel"] for c in json.loads(h["handoff_json"])["channel_order"]]
    assert order[:2] == ["voice", "whatsapp"]
    pipeline.clock.set(h["not_before"])
    b = pipeline.broadcaster()
    for _ in range(36):  # 9 hours in 15-minute ticks: covers the retry gap and the simulated answer delay (< 6 h)
        b.tick(); pipeline.clock.advance(minutes=15)
    attempts = pipeline.store.attempts_for_handoff(h["handoff_id"])
    sent = [(a["channel"], a["delivery_attempt"], a["state"]) for a in attempts if a["sent_at"]]
    assert ("voice", 1, "failed") in sent and ("voice", 2, "failed") in sent and ("whatsapp", 1, "answered") in sent
    assert pipeline.store.get_handoff(h["handoff_id"])["state"] == "answered"
    responses = pipeline.store.list_responses(survey_id=sid).items
    assert {r["failure_code"] for r in responses} == {"voice_busy", "voice_no_answer", None}


def test_silent_farmer_moves_on_after_wait_hours_then_expires(pipeline):
    iid, obj = _find(pipeline.store, resolution_type="direct_action", preferred_channel="telegram")
    sid = survey_id_for(iid)
    h = _schedule_one(pipeline, iid, {sid: ["silent", "silent", "silent"]})
    hj = json.loads(h["handoff_json"])
    wait = hj["channel_order"][0]["wait_hours"]
    pipeline.clock.set(h["not_before"])
    b = pipeline.broadcaster()
    b.tick()
    pipeline.clock.advance(hours=wait - 1); b.tick()
    assert sum(1 for a in pipeline.store.attempts_for_handoff(h["handoff_id"]) if a["sent_at"]) == 1
    pipeline.clock.advance(hours=2); b.tick()
    assert sum(1 for a in pipeline.store.attempts_for_handoff(h["handoff_id"]) if a["sent_at"]) >= 2
    pipeline.clock.set(parse_ist(h["expires_at"])); pipeline.clock.advance(minutes=1); b.tick()
    row = pipeline.store.get_handoff(h["handoff_id"])
    assert row["state"] == "expired"
    codes = {r["failure_code"] for r in pipeline.store.list_responses(survey_id=sid).items}
    assert codes <= {"window_expired", "push_not_opened"} and codes


def _eligible_pairs_for_one_farmer(pipeline, max_gap_days=6):
    """Two normal/low-priority eligible insights of one farmer whose windows open 0..max_gap_days apart."""
    by_farmer: dict[str, list] = {}
    for row in pipeline.store.iter_insights(only_valid=True):
        obj = json.loads(row["raw_json"])
        if obj.get("severity") in ("high", "critical") or obj.get("resolution_type") == "escalate_to_expert":
            continue
        d = pipeline.decide_one(row)
        if d.survey:
            by_farmer.setdefault(obj["farmer_id"], []).append((d.send_window.not_before, obj))
    for farmer, lst in by_farmer.items():
        lst.sort(key=lambda t: t[0])
        for (a_nb, a), (b_nb, b) in zip(lst, lst[1:]):
            if 0 <= (b_nb - a_nb).days <= max_gap_days:
                return farmer, a, b
    raise AssertionError("no suitable pair")


def test_frequency_cap_defers_and_exempts_high_priority(pipeline):
    farmer, first, second = _eligible_pairs_for_one_farmer(pipeline)
    h1 = _schedule_one(pipeline, first["insight_id"], {survey_id_for(first["insight_id"]): ["completed"]})
    h2 = _schedule_one(pipeline, second["insight_id"], {survey_id_for(second["insight_id"]): ["completed"]})
    b = pipeline.broadcaster()
    pipeline.clock.set(h1["not_before"]); b.tick(); pipeline.clock.advance(hours=6); b.tick()
    assert pipeline.store.get_handoff(h1["handoff_id"])["state"] == "answered"
    # Within 7 days of h1 being counted, h2 must be deferred, not sent.
    pipeline.clock.set(max(parse_ist(h2["not_before"]), pipeline.clock.now))
    rep = b.tick()
    assert pipeline.store.get_handoff(h2["handoff_id"])["state"] == "waiting_cap" and rep.cap_deferred_ticks == 1 and rep.sent == 0
    # A high-priority hand-off for the same farmer is exempt.
    with pipeline.store.write() as conn:
        hj = json.loads(h2["handoff_json"]); hj["priority"] = "high"; hj["frequency_cap"]["exempt"] = True
        conn.execute("UPDATE handoffs SET handoff_json = ?, state = 'scheduled' WHERE handoff_id = ?", (json.dumps(hj), h2["handoff_id"]))
        conn.execute("DELETE FROM delivery_attempts WHERE handoff_id = ?", (h2["handoff_id"],))
    rep = b.tick()
    assert rep.sent == 1


def test_opt_out_suppresses_later_surveys_for_that_farmer(pipeline):
    farmer, a, bb = _eligible_pairs_for_one_farmer(pipeline, max_gap_days=60)
    ha = _schedule_one(pipeline, a["insight_id"], {survey_id_for(a["insight_id"]): ["farmer_opted_out"]})
    hb = _schedule_one(pipeline, bb["insight_id"], {survey_id_for(bb["insight_id"]): ["completed"]})
    b = pipeline.broadcaster()
    pipeline.clock.set(ha["not_before"]); b.tick(); pipeline.clock.advance(hours=12); b.tick()
    assert pipeline.store.get_handoff(ha["handoff_id"])["state"] == "declined"
    assert pipeline.store.kv_get(f"optout:{farmer}") == "1"
    pipeline.clock.set(max(parse_ist(hb["not_before"]), pipeline.clock.now)); rep = b.tick()
    assert pipeline.store.get_handoff(hb["handoff_id"])["state"] == "suppressed_opt_out" and rep.sent == 0


def test_two_handoffs_same_tick_respect_cap(pipeline):
    """In-flight sends occupy the cap: two normal surveys for one farmer due at once -> only one is sent."""
    farmer, first, second = _eligible_pairs_for_one_farmer(pipeline, max_gap_days=0)
    h1 = _schedule_one(pipeline, first["insight_id"], {survey_id_for(first["insight_id"]): ["silent"]})
    h2 = _schedule_one(pipeline, second["insight_id"], {survey_id_for(second["insight_id"]): ["silent"]})
    pipeline.clock.set(max(h1["not_before"], h2["not_before"]))
    rep = pipeline.broadcaster().tick()
    assert rep.sent == 1 and rep.cap_deferred_ticks == 1
    states = sorted(pipeline.store.get_handoff(h)["state"] for h in (h1["handoff_id"], h2["handoff_id"]))
    assert states == ["in_progress", "waiting_cap"]


def test_ticks_are_idempotent_and_duplicates_ignored(pipeline):
    iid, obj = _find(pipeline.store, resolution_type="direct_action", preferred_channel="whatsapp")
    sid = survey_id_for(iid)
    h = _schedule_one(pipeline, iid, {sid: ["completed"]})
    pipeline.clock.set(h["not_before"])
    b = pipeline.broadcaster()
    b.tick(); pipeline.clock.advance(hours=6); b.tick()
    snapshot = (pipeline.store.handoff_counts(), pipeline.store.attempt_counts(), pipeline.store.response_counts())
    for _ in range(3):
        rep = b.tick()
        assert rep.sent == rep.answered == rep.failed == 0
    assert (pipeline.store.handoff_counts(), pipeline.store.attempt_counts(), pipeline.store.response_counts()) == snapshot
    # A second answer for an already-answered survey is stored as a duplicate and does not change the answers.
    with pipeline.store.write() as conn:
        rec = pipeline.simulator.react(json.loads(pipeline.store.get_survey(sid)["survey_json"]), "whatsapp", 2, pipeline.clock.now, outcome="completed").record
        attempt = {"attempt_key": f"{h['handoff_id']}:whatsapp:2", "handoff_id": h["handoff_id"], "survey_id": sid, "channel": "whatsapp", "channel_index": 0, "delivery_attempt": 2}
        pipeline.store.upsert_attempt(conn, {**attempt, "state": "awaiting", "scheduled_for": "x", "sent_at": "x", "outcome_status": None, "failure_code": None, "response_key": None, "created_at": "x", "updated_at": "x"})
    from mel_agent.delivery.broadcaster import TickReport
    rep = TickReport(at="x")
    b._apply_record(h["handoff_id"], json.loads(pipeline.store.get_survey(sid)["survey_json"]), attempt, rec, pipeline.clock.now, rep)
    assert rep.duplicates_ignored == 1
    dup = [r for r in pipeline.store.list_responses(survey_id=sid).items if r["status"] == "duplicate"]
    assert len(dup) == 1 and dup[0]["failure_code"] == "duplicate_answer"
    assert pipeline.store.response_counts()["by_status"]["completed"] == 1


def test_clock_only_parses_ist():
    c = SimulatedClock("2026-11-01T00:00:00+05:30")
    c.advance(days=1, hours=7)
    assert c.iso() == "2026-11-02T07:00:00+05:30"
    with pytest.raises(Exception):
        SimulatedClock("2026-11-01T00:00:00Z")
