"""Stateful scheduling behavior, including separate SQLite worker connections."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from threading import Barrier

import pytest

from farmerloop.generate_contextual import ContextualSurveyGenerator
from farmerloop.respond import ItemObservation
from farmerloop.scheduler import IST, Scheduler
from farmerloop.simulate import format_raw
from farmerloop.timing import compute_window
from tests.helpers import make_insight

CREATED = datetime(2026, 12, 4, 10, tzinfo=IST)
SEND = datetime(2026, 12, 6, 9, tzinfo=IST)


def job(scheduler, number=1, *, farmer="F-000001", severity="medium", channel="whatsapp",
        created="2026-12-04T09:00:00+05:30", timing="two_to_five_days", now=CREATED):
    ins = make_insight(insight_id=f"I-{number:06d}", farmer_id=farmer,
                       conversation_language="en-IN", severity=severity,
                       preferred_channel=channel, created_at=created,
                       verification={"needed": True, "timing": timing, "method": "none"},
                       advice_summary="Advised to spray a recommended insecticide as per the label.")
    window = compute_window(ins.created_at, ins.verification.timing, ins.action_window_days)
    survey = ContextualSurveyGenerator().generate(ins, window)
    result = scheduler.enqueue(ins, survey, window, now=now)
    return survey.survey_id, (ins, survey, window), result


@pytest.fixture
def scheduler(tmp_path):
    with Scheduler(tmp_path / "schedule.sqlite3") as store:
        yield store


def finish(scheduler, claim, case="completed", *, now=SEND + timedelta(minutes=25)):
    return scheduler.complete_simulated(claim["attempt_id"], case, now=now)


def test_duplicate_enqueue_and_conflicting_content(scheduler):
    sid, (ins, survey, window), _ = job(scheduler)
    assert scheduler.enqueue(ins, survey, window, now=CREATED + timedelta(minutes=1))["status"] == "duplicate"
    survey.rationale += " Updated."
    with pytest.raises(ValueError, match="Conflicting survey ID"):
        scheduler.enqueue(ins, survey, window, now=CREATED + timedelta(minutes=2))
    assert len(scheduler.snapshot()["jobs"]) == 1


def test_weekly_cap_counts_once_and_replay_is_idempotent(scheduler):
    a, _, _ = job(scheduler)
    b, _, _ = job(scheduler, 2)
    claim = scheduler.claim(a, now=SEND)
    assert claim["decision"] == "claimed"
    assert scheduler.claim(a, now=SEND)["decision"] == "in_flight"
    assert scheduler.claim(b, now=SEND)["reason"] == "unresolved_attempt_reservation"
    assert finish(scheduler, claim)["status"] == "accepted"
    assert finish(scheduler, claim)["status"] == "duplicate"
    assert scheduler.claim(b, now=SEND + timedelta(minutes=25))["reason"] == "weekly_cap"
    state = scheduler.snapshot()
    assert len(state["attempts"]) == len(state["cap_events"]) == 1


def test_failed_delivery_releases_reservation_and_does_not_count(scheduler):
    a, _, _ = job(scheduler)
    b, _, _ = job(scheduler, 2)
    claim = scheduler.claim(a, now=SEND)
    finish(scheduler, claim, "wa_undelivered", now=SEND)
    assert not scheduler.snapshot()["cap_events"]
    assert scheduler.claim(b, now=SEND)["decision"] == "claimed"


def test_cross_channel_fallback_rechecks_guards_and_counts_one_survey(scheduler):
    sid, _, _ = job(scheduler, channel="app")
    claim = scheduler.claim(sid, now=SEND)
    assert claim["channel"] == "app"
    finish(scheduler, claim, "push_token_invalid", now=SEND)
    retry = scheduler.claim(sid, now=SEND)
    assert retry["channel"] == "whatsapp"
    assert retry["delivery_attempt"] == 1
    finish(scheduler, retry)
    state = scheduler.snapshot()
    assert len(state["attempts"]) == 2
    assert len(state["cap_events"]) == 1


def test_high_priority_bypasses_cap_but_still_counts(scheduler):
    a, _, _ = job(scheduler)
    high, _, _ = job(scheduler, 2, severity="high")
    normal, _, _ = job(scheduler, 3)
    finish(scheduler, scheduler.claim(a, now=SEND))
    when = SEND + timedelta(minutes=30)
    claim = scheduler.claim(high, now=when)
    assert claim["decision"] == "claimed"
    finish(scheduler, claim, now=when + timedelta(minutes=25))
    assert len(scheduler.snapshot()["cap_events"]) == 2
    assert scheduler.claim(normal, now=when + timedelta(minutes=25))["reason"] == "weekly_cap"


def test_optout_cancels_queued_and_blocks_high_priority_after_restart(tmp_path):
    path = tmp_path / "persist.sqlite3"
    with Scheduler(path) as store:
        a, _, _ = job(store)
        high, _, _ = job(store, 2, severity="high")
        claim = store.claim(a, now=SEND)
        finish(store, claim, "farmer_opted_out")
    with Scheduler(path) as store:
        assert store.claim(high, now=SEND + timedelta(minutes=26))["reason"] == "farmer_opted_out"
        future, _, _ = job(store, 3, severity="high", created="2026-12-06T09:00:00+05:30", now=SEND + timedelta(minutes=26))
        assert store.claim(future, now=SEND + timedelta(days=2))["reason"] == "farmer_opted_out"
        assert len(store.snapshot()["optouts"]) == 1


def test_decline_is_not_optout(scheduler):
    a, _, _ = job(scheduler)
    high, _, _ = job(scheduler, 2, severity="high")
    finish(scheduler, scheduler.claim(a, now=SEND), "farmer_declined")
    assert not scheduler.snapshot()["optouts"]
    assert scheduler.claim(high, now=SEND + timedelta(minutes=25))["decision"] == "claimed"


def test_optout_applies_to_previously_queued_retry(scheduler):
    sid, _, _ = job(scheduler, channel="voice", severity="high")
    finish(scheduler, scheduler.claim(sid, now=SEND), "voice_busy", now=SEND)
    scheduler.opt_out("F-000001", verified_farmer_id="F-000001", now=SEND)
    assert scheduler.claim(sid, now=SEND + timedelta(minutes=10))["reason"] == "farmer_opted_out"


def test_identity_mismatch_cannot_change_target_preferences(scheduler):
    sid, _, _ = job(scheduler)
    claim = scheduler.claim(sid, now=SEND)
    record = finish(scheduler, claim, "identity_mismatch")["response"]
    assert record["status"] == "identity_mismatch"
    assert not scheduler.snapshot()["cap_events"]
    with pytest.raises(ValueError, match="identity"):
        scheduler.opt_out("F-000001", verified_farmer_id="F-OTHER", now=SEND + timedelta(minutes=25))
    assert not scheduler.snapshot()["optouts"]


def test_cap_and_unresolved_attempt_persist_after_restart(tmp_path):
    path = tmp_path / "persist.sqlite3"
    with Scheduler(path) as store:
        a, _, _ = job(store)
        b, _, _ = job(store, 2)
        claim = store.claim(a, now=SEND)
    with Scheduler(path) as store:
        assert store.claim(a, now=SEND)["decision"] == "in_flight"
        assert store.claim(b, now=SEND)["reason"] == "unresolved_attempt_reservation"
        finish(store, claim)
    with Scheduler(path) as store:
        assert store.claim(b, now=SEND + timedelta(minutes=25))["reason"] == "weekly_cap"


def test_exact_seven_day_boundary_and_other_farmers(scheduler):
    a, _, _ = job(scheduler)
    other, _, _ = job(scheduler, 2, farmer="F-OTHER")
    finish(scheduler, scheduler.claim(a, now=SEND))
    assert scheduler.claim(other, now=SEND + timedelta(minutes=25))["decision"] == "claimed"
    b, _, _ = job(scheduler, 3, created="2026-12-11T09:00:00+05:30", now=SEND + timedelta(days=5))
    # First actual display is the simulator's opened timestamp, 09:20.
    release = SEND + timedelta(days=7, minutes=20)
    assert scheduler.claim(b, now=release - timedelta(microseconds=1))["reason"] == "weekly_cap"
    assert scheduler.claim(b, now=release)["decision"] == "claimed"


def test_retry_delay_and_limit_are_enforced(scheduler):
    sid, _, _ = job(scheduler, channel="voice", severity="high")
    when = SEND
    for number in (1, 2, 3):
        claim = scheduler.claim(sid, now=when)
        assert claim["delivery_attempt"] == number
        finish(scheduler, claim, "voice_busy", now=when)
        if number < 3:
            assert scheduler.claim(sid, now=when + timedelta(minutes=9))["reason"] == "not_due"
        when += timedelta(minutes=10)
    assert scheduler.claim(sid, now=when)["reason"] == "retry_exhausted"
    assert len(scheduler.snapshot()["attempts"]) == 3


def test_counted_retry_does_not_refresh_cap_timestamp(scheduler):
    sid, _, _ = job(scheduler, channel="voice", severity="high")
    claim = scheduler.claim(sid, now=SEND)
    finish(scheduler, claim, "voice_call_dropped", now=SEND + timedelta(minutes=20))
    first = scheduler.snapshot()["cap_events"][0]["asked_us"]
    retry = scheduler.claim(sid, now=SEND + timedelta(minutes=30))
    finish(scheduler, retry, now=SEND + timedelta(minutes=55))
    assert scheduler.snapshot()["cap_events"][0]["asked_us"] == first


def test_display_counts_immediately_even_before_answer(scheduler):
    a, _, _ = job(scheduler)
    b, _, _ = job(scheduler, 2)
    claim = scheduler.claim(a, now=SEND)
    shown = SEND + timedelta(minutes=2)
    scheduler.acknowledge_shown(claim["attempt_id"], shown_at=shown, verified_farmer_id="F-000001", now=shown)
    assert scheduler.claim(b, now=shown)["reason"] == "weekly_cap"
    with pytest.raises(ValueError, match="display"):
        finish(scheduler, claim, "wa_undelivered", now=shown)
    assert scheduler.snapshot()["attempts"][0]["response"] is None
    finish(scheduler, claim)
    assert len(scheduler.snapshot()["cap_events"]) == 1


@pytest.mark.parametrize("when,reason", [
    (datetime(2026, 12, 5, 9, tzinfo=IST), "not_due"),
    (datetime(2026, 12, 6, 6, tzinfo=IST), "not_due"),
    (datetime(2026, 12, 7, 6, tzinfo=IST), "outside_send_hours"),
    (datetime(2026, 12, 7, 20, tzinfo=IST), "outside_send_hours"),
    (datetime(2026, 12, 9, 19, 0, 1, tzinfo=IST), "send_window_closed"),
    (datetime(2026, 12, 9, 19, 0, 0, 1, tzinfo=IST), "send_window_closed"),
    (datetime(2026, 12, 11, 19, tzinfo=IST), "expired"),
])
def test_send_boundaries(scheduler, when, reason):
    sid, _, _ = job(scheduler)
    assert scheduler.claim(sid, now=when)["reason"] == reason
    assert not scheduler.snapshot()["attempts"]


def test_future_response_is_rejected_atomically(scheduler):
    sid, _, _ = job(scheduler)
    claim = scheduler.claim(sid, now=SEND)
    with pytest.raises(ValueError, match="future"):
        finish(scheduler, claim, now=SEND)
    assert not scheduler.snapshot()["cap_events"]
    assert scheduler.snapshot()["attempts"][0]["response"] is None
    assert finish(scheduler, claim)["status"] == "accepted"


def test_clock_cannot_go_backwards_and_runs_are_isolated(tmp_path):
    path = tmp_path / "shared.sqlite3"
    with Scheduler(path, run_id="first") as store:
        sid, _, _ = job(store)
        store.claim(sid, now=SEND)
        with pytest.raises(ValueError, match="backwards"):
            store.claim(sid, now=CREATED)
    with Scheduler(path, run_id="second") as store:
        sid, _, _ = job(store)
        assert store.claim(sid, now=SEND)["decision"] == "claimed"
        assert not store.snapshot()["optouts"]


def test_changed_policy_cannot_reuse_existing_run(tmp_path):
    path = tmp_path / "shared.sqlite3"
    with Scheduler(path):
        pass
    with pytest.raises(ValueError, match="policy changed"):
        Scheduler(path, max_channel_attempts=4)


@pytest.mark.parametrize("limit", [0, -1, 6, 1.5, True])
def test_retry_limit_cannot_exceed_official_response_contract(tmp_path, limit):
    with pytest.raises(ValueError, match="integer from 1 to 5"):
        Scheduler(tmp_path / "invalid.sqlite3", max_channel_attempts=limit)


@pytest.mark.parametrize("same_survey", [True, False])
def test_two_workers_cannot_claim_duplicate_or_two_normal_surveys(tmp_path, same_survey):
    path = tmp_path / "concurrent.sqlite3"
    with Scheduler(path) as store:
        a, _, _ = job(store)
        b, _, _ = job(store, 2)
    barrier = Barrier(2)
    def worker(sid):
        with Scheduler(path) as store:
            barrier.wait(timeout=5)
            return store.claim(sid, now=SEND)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(worker, sid) for sid in (a, a if same_survey else b)]
        results = [f.result(timeout=15) for f in futures]
    assert sum(r["decision"] == "claimed" for r in results) == 1
    with Scheduler(path) as store:
        assert len(store.snapshot()["attempts"]) == 1


def test_actual_tap_observations_flow_through_response_builder(scheduler):
    sid, _, _ = job(scheduler)
    claim = scheduler.claim(sid, now=SEND)
    survey = claim["survey"]
    items = {}
    for item in survey["items"]:
        raw, kind = format_raw(survey, item, item["options"][0]["value"], claim["channel"])
        items[item["item_id"]] = ItemObservation(True, raw, kind)
    args = dict(items=items, timestamps={"sent": claim["sent_at"], "delivered": (SEND + timedelta(minutes=1)).isoformat(),
                                        "opened": None, "answered": (SEND + timedelta(minutes=2)).isoformat()},
                recorded_at=(SEND + timedelta(minutes=2)).isoformat(), answered_by=survey["farmer_id"],
                now=SEND + timedelta(minutes=2))
    assert scheduler.complete(claim["attempt_id"], **args)["response"]["complete"]
    assert scheduler.complete(claim["attempt_id"], **args)["status"] == "duplicate"
    args["raw_event"] = "conflicting history"
    with pytest.raises(ValueError, match="Conflicting final"):
        scheduler.complete(claim["attempt_id"], **args)


def test_optout_observation_requires_identity_and_rolls_back(scheduler):
    sid, _, _ = job(scheduler)
    claim = scheduler.claim(sid, now=SEND)
    with pytest.raises(ValueError, match="verified survey farmer"):
        scheduler.complete(claim["attempt_id"], items={}, timestamps={"sent": claim["sent_at"]},
                           recorded_at=claim["sent_at"], answered_by=None, event="farmer_opted_out", now=SEND)
    assert not scheduler.snapshot()["optouts"]
    assert not scheduler.snapshot()["cap_events"]


def test_invalid_choice_and_wrong_sent_time_do_not_change_state(scheduler):
    sid, _, _ = job(scheduler, channel="app")
    claim = scheduler.claim(sid, now=SEND)
    with pytest.raises(ValueError):
        scheduler.complete(claim["attempt_id"], items={"q1": ItemObservation(True, "made_up", "sheet_tap")},
                           timestamps={"sent": claim["sent_at"]}, recorded_at=claim["sent_at"],
                           answered_by="F-000001", now=SEND)
    with pytest.raises(ValueError, match="reserved attempt"):
        scheduler.complete(claim["attempt_id"], items={}, timestamps={"sent": CREATED.isoformat()},
                           recorded_at=claim["sent_at"], answered_by=None, event="push_token_invalid", now=SEND)
    assert scheduler.snapshot()["attempts"][0]["response"] is None


@pytest.mark.parametrize("channel", ["app", "web", "whatsapp", "telegram", "voice"])
def test_preexisting_optout_blocks_all_channels_even_high_priority(scheduler, channel):
    scheduler.opt_out("F-000001", verified_farmer_id="F-000001", now=CREATED)
    sid, _, _ = job(scheduler, channel=channel, severity="high")
    assert scheduler.claim(sid, now=SEND)["reason"] == "farmer_opted_out"
    assert not scheduler.snapshot()["attempts"]


def test_retry_cannot_bypass_night_hours_or_closed_window(scheduler):
    sid, _, _ = job(scheduler, channel="voice", severity="high")
    when = datetime(2026, 12, 9, 18, 55, tzinfo=IST)
    claim = scheduler.claim(sid, now=when)
    finish(scheduler, claim, "voice_busy", now=when)
    assert scheduler.claim(sid, now=when + timedelta(minutes=10))["reason"] == "send_window_closed"
    assert len(scheduler.snapshot()["attempts"]) == 1


def test_capped_job_eventually_drops_instead_of_sending_after_window(scheduler):
    a, _, _ = job(scheduler)
    b, _, _ = job(scheduler, 2)
    finish(scheduler, scheduler.claim(a, now=SEND))
    assert scheduler.claim(b, now=SEND + timedelta(minutes=25))["reason"] == "weekly_cap"
    assert scheduler.claim(b, now=datetime(2026, 12, 9, 19, 0, 1, tzinfo=IST))["reason"] == "send_window_closed"


def test_unknown_attempt_is_never_automatically_resent(scheduler):
    sid, _, _ = job(scheduler)
    scheduler.claim(sid, now=SEND)
    assert scheduler.claim(sid, now=SEND + timedelta(days=20))["decision"] == "in_flight"
    assert len(scheduler.snapshot()["attempts"]) == 1


def test_cap_count_without_display_receipt_uses_recorded_time(scheduler):
    sid, _, _ = job(scheduler)
    claim = scheduler.claim(sid, now=SEND)
    recorded = SEND + timedelta(minutes=30)
    scheduler.complete(claim["attempt_id"], items={}, timestamps={"sent": claim["sent_at"]},
                       recorded_at=recorded.isoformat(), answered_by="F-000001", event="farmer_declined", now=recorded)
    assert scheduler.snapshot()["cap_events"][0]["asked_us"] > scheduler.snapshot()["attempts"][0]["claimed_us"]


def test_fractional_clock_projects_records_to_official_second_precision(scheduler):
    sid, _, _ = job(scheduler)
    when = SEND + timedelta(microseconds=123456)
    claim = scheduler.claim(sid, now=when)
    result = finish(scheduler, claim, now=when + timedelta(minutes=25))
    assert result["response"]["timestamps"]["sent"] == claim["sent_at"]
    assert claim["sent_at"] == SEND.isoformat()


def test_late_answers_without_answer_timestamp_are_not_accepted(scheduler):
    sid, _, _ = job(scheduler, channel="app")
    claim = scheduler.claim(sid, now=SEND)
    late = datetime(2026, 12, 11, 19, tzinfo=IST)
    with pytest.raises(ValueError, match="Late answers"):
        scheduler.complete(claim["attempt_id"], items={"q1": ItemObservation(True, "yes", "sheet_tap")},
                           timestamps={"sent": claim["sent_at"]}, recorded_at=late.isoformat(),
                           answered_by="F-000001", now=late)
    assert scheduler.snapshot()["attempts"][0]["response"] is None


def test_demo_reset_is_explicit_and_isolated(tmp_path):
    path = tmp_path / "runs.sqlite3"
    with Scheduler(path, run_id="default") as store:
        job(store)
        with pytest.raises(ValueError, match="demo-"):
            store.reset_demo(confirm_run_id="default")
    with Scheduler(path, run_id="demo-one") as store:
        sid, _, _ = job(store)
        finish(store, store.claim(sid, now=SEND), "farmer_opted_out")
        with pytest.raises(ValueError, match="exact"):
            store.reset_demo(confirm_run_id="demo-other")
        store.reset_demo(confirm_run_id="demo-one")
        state = store.snapshot()
        assert state["clock"] is None
        assert all(not state[t] for t in ("jobs", "attempts", "cap_events", "optouts", "decisions"))
        job(store)  # Reset permits a fresh simulated timeline.
    with Scheduler(path, run_id="default") as store:
        assert len(store.snapshot()["jobs"]) == 1


def test_scripted_demo_restarts_and_preserves_protections(tmp_path):
    from farmerloop.scheduler_demo import run
    path = tmp_path / "demo.sqlite3"
    report = run(path)
    assert report["counted_surveys"] == 3
    assert report["opted_out_farmers"] == 1
    assert report["attempts"] == 4
    reasons = [row["reason"] for row in report["steps"]]
    assert "weekly_cap" in reasons
    assert "farmer_opted_out" in reasons
    assert "awaiting_attempt_outcome" in reasons
    with pytest.raises(ValueError, match="already has history"):
        run(path)
    assert run(path, reset=True)["steps"] == report["steps"]


def test_accepted_taps_need_verified_identity(scheduler):
    sid, _, _ = job(scheduler, channel="app")
    claim = scheduler.claim(sid, now=SEND)
    with pytest.raises(ValueError, match="Accepted answers require"):
        scheduler.complete(claim["attempt_id"], items={"q1": ItemObservation(True, "yes", "sheet_tap")},
                           timestamps={"sent": claim["sent_at"]}, recorded_at=claim["sent_at"],
                           answered_by=None, now=SEND)
    assert scheduler.snapshot()["attempts"][0]["response"] is None


def test_scheduler_rejects_ineligible_source_before_storing_job(scheduler):
    _, (ins, survey, window), _ = job(scheduler)
    ins.severity = "critical"
    with pytest.raises(ValueError, match="not eligible"):
        scheduler.enqueue(ins, survey, window, now=CREATED)
    assert len(scheduler.snapshot()["jobs"]) == 1


def test_normal_retry_excludes_its_own_prior_cap_event(scheduler):
    sid, _, _ = job(scheduler)
    claim = scheduler.claim(sid, now=SEND)
    result = finish(scheduler, claim, "free_text_instead_of_choice")
    assert result["response"]["counts_toward_cap"] is True
    retry = scheduler.claim(sid, now=SEND + timedelta(minutes=25))
    assert retry["decision"] == "claimed"
    finish(scheduler, retry, now=SEND + timedelta(minutes=50))
    assert len(scheduler.snapshot()["cap_events"]) == 1


def test_display_identity_and_future_timestamp_are_rejected(scheduler):
    sid, _, _ = job(scheduler)
    claim = scheduler.claim(sid, now=SEND)
    with pytest.raises(ValueError, match="identity"):
        scheduler.acknowledge_shown(claim["attempt_id"], shown_at=SEND,
                                    verified_farmer_id="F-WRONG", now=SEND)
    with pytest.raises(ValueError, match="future"):
        scheduler.acknowledge_shown(claim["attempt_id"], shown_at=SEND + timedelta(hours=1),
                                    verified_farmer_id="F-000001", now=SEND)
    assert not scheduler.snapshot()["cap_events"]
