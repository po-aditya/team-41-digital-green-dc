"""End-to-end pipeline properties over the real dataset (offline)."""

from __future__ import annotations

import json

import pytest

from mel_agent.generation.providers import FailingProvider
from mel_agent.pipeline import Pipeline
from mel_agent.rules.scheduling import survey_id_for
from mel_agent.time_utils import parse_ist

NOW = "2026-11-01T00:00:00+05:30"


@pytest.fixture(scope="module")
def full_run(settings, ingested_db_path, tmp_path_factory, registry):
    import shutil

    from mel_agent.store import Store

    dst = tmp_path_factory.mktemp("full") / "full.db"
    shutil.copy(ingested_db_path, dst)
    store = Store(dst)
    p = Pipeline(settings, store, registry)
    decide = p.decide_all(NOW)
    gen = p.generate_and_schedule(NOW)
    return p, decide, gen


def test_decisions_cover_every_row_with_expected_distribution(full_run):
    p, decide, _ = full_run
    assert decide["decided"] == 6999
    by = decide["by_internal_reason"]
    assert by["schema_invalid"] == 50 and by["junk_insight"] == 673
    assert by["nothing_to_verify"] == 1287 and by["waiting_for_details"] == 875 and by["no_check_needed"] == 1312
    assert by["critical_needs_human_call"] == 25
    assert by["survey"] == 2628 and by["window_after_season"] == 111 and by["crop_already_harvested"] == 2
    assert by["window_truncated_by_season_end"] == 36  # two-day minimum vs 31 March: held back, see IMPLEMENTATION_PLAN
    assert sum(by.values()) == 6999


def test_every_eligible_insight_got_a_valid_survey_and_handoff(full_run, registry):
    p, _, gen = full_run
    assert gen.processed == gen.surveys_accepted == gen.handoffs_created == 2628 and gen.surveys_rejected == 0
    assert p.store.survey_counts() == {"validated": 2628} and p.store.handoff_counts() == {"scheduled": 2628}
    sample = p.store.list_handoffs(limit=200).items
    for h in sample:
        hj = json.loads(p.store.get_handoff(h["handoff_id"])["handoff_json"])
        assert not registry.errors("schedule_handoff", hj)
        assert not registry.errors("survey", hj["survey"])


def test_no_suppressed_or_quarantined_insight_has_a_handoff(full_run):
    p, _, _ = full_run
    with p.store.read() as conn:
        rows = conn.execute("SELECT d.insight_id FROM decisions d JOIN handoffs h ON h.survey_id = ? || substr(d.insight_id, 3) WHERE d.decision <> 'survey'", ("S-",)).fetchall()
    assert rows == []
    with p.store.read() as conn:
        n = conn.execute("SELECT COUNT(*) FROM handoffs h JOIN decisions d ON d.insight_id = 'I-' || substr(h.survey_id, 3) WHERE d.decision = 'survey'").fetchone()[0]
    assert n == 2628


def test_temporal_consistency_of_all_handoffs(full_run, rules):
    p, _, _ = full_run
    season_end = parse_ist("2027-03-31T19:00:00+05:30")
    with p.store.read() as conn:
        rows = conn.execute("SELECT h.not_before, h.not_after, h.expires_at, i.created_at FROM handoffs h JOIN insights i ON i.insight_id = 'I-' || substr(h.survey_id, 3)").fetchall()
    assert len(rows) == 2628
    for nb, na, ex, created in rows:
        nb_d, na_d, ex_d, c_d = parse_ist(nb), parse_ist(na), parse_ist(ex), parse_ist(created)
        assert nb_d.date() > c_d.date()                        # never on the advice day
        assert nb_d.strftime("%H:%M") == "07:00" and na_d.strftime("%H:%M") == "19:00"
        assert na_d <= season_end                              # nothing after 31 March
        assert (na_d.date() - nb_d.date()).days >= 2 or na_d == season_end  # at least two days wide unless clamped
        assert (ex_d - na_d).days == rules.expiry_days_after_window


def test_survey_ids_unique_and_language_follows_conversation(full_run):
    p, _, _ = full_run
    with p.store.read() as conn:
        dup = conn.execute("SELECT COUNT(*) - COUNT(DISTINCT survey_id) FROM surveys").fetchone()[0]
        mismatch = conn.execute("SELECT COUNT(*) FROM surveys s JOIN insights i ON i.insight_id = s.insight_id WHERE s.language <> i.conversation_language").fetchone()[0]
        langs = dict(conn.execute("SELECT language, COUNT(*) FROM surveys GROUP BY language").fetchall())
    assert dup == 0 and mismatch == 0
    assert set(langs) == {"hi-IN", "en-IN"} and langs["hi-IN"] > langs["en-IN"]


def test_rerun_is_idempotent(full_run):
    p, _, _ = full_run
    again = p.generate_and_schedule(NOW)
    assert again.processed == 0 and again.skipped_existing == 2628
    decide_again = p.decide_all(NOW)
    assert decide_again["decided"] == 6999 and p.store.handoff_counts() == {"scheduled": 2628}


def test_generation_telemetry_is_recorded(full_run):
    _, _, gen = full_run
    d = gen.to_dict()
    assert d["generation_latency_ms"]["count"] == 2628 and d["generation_latency_ms"]["p50"] is not None
    assert d["estimated_cost_usd"] == 0.0 and d["usage"] == {}


def test_failed_generation_never_schedules(pipeline, settings, registry):
    from mel_agent.generation.generator import SurveyGenerator

    p = pipeline
    p.generator = SurveyGenerator(settings.model_copy(update={"generation_fallback_to_template": False}), registry, FailingProvider(), fallback=None)
    row = next(r for r in p.store.iter_insights(only_valid=True) if json.loads(r["raw_json"]).get("resolution_type") == "direct_action"
               and (json.loads(r["raw_json"]).get("verification") or {}).get("needed") and json.loads(r["raw_json"]).get("severity") != "critical")
    out = p.process_insight(row["insight_id"], NOW)
    assert out["generation"]["status"] == "rejected"
    sid = survey_id_for(row["insight_id"])
    assert p.store.get_survey(sid)["status"] == "rejected" and p.store.get_handoff_for_survey(sid) is None
    # A later run with a working provider picks it up (nothing was scheduled, so it is still pending).
    p.generator = SurveyGenerator(settings, registry)
    out = p.process_insight(row["insight_id"], NOW)
    assert out["generation"]["status"] == "scheduled"


def test_process_unknown_insight(pipeline):
    assert pipeline.process_insight("I-999999", NOW)["status"] == "unknown_insight"


def test_full_season_broadcast_properties(full_run, registry):
    """Run the simulated season over a 120-hand-off slice and check delivery-state invariants."""
    p, _, _ = full_run
    import shutil

    from mel_agent.delivery.clock import SimulatedClock
    from mel_agent.store import Store

    # Work on a copy restricted to the earliest 120 hand-offs so the test stays fast.
    dst = p.store.path + ".slice"
    p.store.checkpoint()
    shutil.copy(p.store.path, dst)
    store = Store(dst)
    with store.write() as conn:
        keep = [r[0] for r in conn.execute("SELECT handoff_id FROM handoffs ORDER BY not_before, handoff_id LIMIT 120")]
        conn.execute(f"DELETE FROM handoffs WHERE handoff_id NOT IN ({','.join('?' * len(keep))})", keep)
    q = Pipeline(p.settings, store, registry, clock=SimulatedClock(NOW))
    last = max(h["expires_at"] for h in store.list_handoffs(limit=200).items)
    q.run_broadcaster(last, step_minutes=120)
    q.clock.advance(hours=3); q.broadcaster().tick()
    states = store.handoff_counts()
    assert sum(states.values()) == 120 and not (set(states) & {"scheduled", "in_progress", "waiting_cap"})
    with store.read() as conn:
        # every stored response is schema-valid and belongs to a hand-off
        for (rec,) in conn.execute("SELECT record_json FROM responses"):
            assert not registry.errors("response", json.loads(rec))
        orphans = conn.execute("SELECT COUNT(*) FROM responses r LEFT JOIN handoffs h ON h.survey_id = r.survey_id WHERE h.handoff_id IS NULL").fetchone()[0]
        assert orphans == 0
        # at most one accepted answer set per survey
        multi = conn.execute("SELECT survey_id FROM responses WHERE status IN ('completed','partial','negative_outcome') GROUP BY survey_id HAVING COUNT(*) > 1").fetchall()
        assert multi == []
        # a farmer never has two counted surveys within 7 days unless one was high priority (exempt)
        rows = conn.execute("SELECT farmer_id, counted_at, priority FROM handoffs WHERE counted_at IS NOT NULL ORDER BY farmer_id, counted_at").fetchall()
    by_farmer: dict[str, list] = {}
    for f, at, prio in rows:
        by_farmer.setdefault(f, []).append((parse_ist(at), prio))
    for f, lst in by_farmer.items():
        for (a, pa), (b, pb) in zip(lst, lst[1:]):
            assert (b - a).days >= 7 or pb == "high" or pa == "high", (f, a, b)
