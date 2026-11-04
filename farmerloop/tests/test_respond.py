"""Unit tests for response building, simulation and the feedback demo."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime

import pytest

from farmerloop import config, outcomes
from farmerloop.outcomes import ResponseConfigError
from farmerloop.respond import ItemObservation as Obs, build_response, interpret
from farmerloop.simulate import CASES, SIMULATED_OTHER_FARMER, simulate
from farmerloop.validate import validate

SCEN = config.PARTICIPANT_PACK / "json" / "scenarios"
POTATO = json.loads((SCEN / "3-potato-blight-wait" / "survey.hi-IN.json").read_text(encoding="utf-8"))
COW = json.loads((SCEN / "4-cow-vet-escalation" / "survey.hi-IN.json").read_text(encoding="utf-8"))
SID = POTATO["survey_id"]
TS = {"sent": "2026-12-06T09:00:00+05:30", "delivered": "2026-12-06T09:01:00+05:30",
      "opened": "2026-12-06T09:20:00+05:30", "answered": "2026-12-06T09:25:00+05:30"}
TS_TG = {**TS, "opened": None}


def tap(v):
    return Obs(shown=True, raw_input=str(v), input_kind="sheet_tap")


def build(survey=POTATO, channel="app", items=None, ts=None, answered_by="__farmer__", **kw):
    if answered_by == "__farmer__":
        answered_by = survey["farmer_id"]
    if ts is None:
        ts = TS_TG if channel == "telegram" else TS
    return build_response(survey, channel=channel, items=items or {}, timestamps=ts,
                          recorded_at=ts["answered"] or ts["sent"], response_key="rk-test",
                          answered_by=answered_by, **kw)


# ---- success states and follow-up -------------------------------------------
def test_completed_healthy_answers():
    r = build(items={"q1": tap("yes"), "q2": tap("no_new"), "q3": tap(5)})
    assert (r["status"], r["complete"], r["needs_follow_up"]) == ("completed", True, False)
    assert r["answers"] == {"q1": "yes", "q2": "no_new", "q3": 5}  # scale stays an integer
    assert r["sheet_outcome"] == "finished"
    assert r["farmerchat_reply"] == {"http_status": 201, "outcome": "accepted"}
    assert validate("response", r) == []


def test_flagged_option_gives_negative_outcome():
    r = build(items={"q1": tap("yes"), "q2": tap("spreading"), "q3": tap(4)})
    assert r["status"] == "negative_outcome"
    assert r["follow_up_reasons"] == ["crop_or_animal_damaged"]


def test_scale_at_threshold_flags_follow_up_but_above_does_not():
    at = build(items={"q1": tap("yes"), "q2": tap("no_new"), "q3": tap(1)})
    above = build(items={"q1": tap("yes"), "q2": tap("no_new"), "q3": tap(2)})
    assert at["follow_up_reasons"] == ["advice_did_not_work"]
    assert above["needs_follow_up"] is False


def test_follow_up_reasons_are_unique_and_in_question_order():
    r = build(COW, channel="whatsapp", items={
        "q1": Obs(True, f"{COW['survey_id']}|q1|no", "button_reply"),
        "q2": Obs(True, f"{COW['survey_id']}|q2|worse", "button_reply")})
    assert r["follow_up_reasons"] == ["could_not_reach_expert", "crop_or_animal_damaged"]


def test_partial_without_follow_up_stays_partial():
    r = build(channel="whatsapp", items={"q1": Obs(True, f"{SID}|q1|yes", "button_reply"),
                                         "q2": Obs(shown=True)})
    assert (r["status"], r["complete"]) == ("partial", False)
    assert [i["result"] for i in r["items"]] == ["answered", "skipped", "not_reached"]


def test_negative_takes_precedence_over_partial_only_for_accepted_flagged_answer():
    r = build(channel="whatsapp", items={"q1": Obs(True, f"{SID}|q1|yes", "button_reply"),
                                         "q2": Obs(True, f"{SID}|q2|spreading", "list_reply")})
    assert r["status"] == "negative_outcome" and r["complete"] is False


def test_sheet_closed_partway_with_flagged_answer_is_negative_but_keeps_sheet_outcome():
    r = build(items={"q1": tap("yes"), "q2": tap("white_growth"), "q3": Obs(shown=True)},
              event="sheet_closed_partway")
    assert r["status"] == "negative_outcome"
    assert r["sheet_outcome"] == "closed_partway"


def test_sheet_closed_partway_without_flag_is_partial():
    r = build(items={"q1": tap("yes"), "q2": Obs(shown=True)}, event="sheet_closed_partway")
    assert (r["status"], r["sheet_outcome"]) == ("partial", "closed_partway")


def test_skipped_question_never_triggers_follow_up():
    r = build(items={"q1": tap("yes"), "q2": Obs(shown=True), "q3": tap(5)})
    assert r["needs_follow_up"] is False


def test_invalid_answer_never_triggers_follow_up():
    # keypad 9 has no option behind it on q2 (4 options)
    r = build(channel="voice", items={"q1": Obs(True, "हाँ", "speech"),
                                      "q2": Obs(True, "9", "keypad", attempts=2)})
    assert r["items"][1]["result"] == "invalid"
    assert r["needs_follow_up"] is False


def test_discarded_flagged_answer_never_triggers_follow_up():
    r = build(items={"q2": tap("spreading")}, event="duplicate_answer")
    assert r["items"][1]["result"] == "discarded"
    assert (r["answers"], r["needs_follow_up"]) == ({}, False)


# ---- invalid FARMER input -> invalid_input under the rules -------------------
@pytest.mark.parametrize("channel, obs, code", [
    ("whatsapp", Obs(True, "पता नहीं", "free_text"), "free_text_instead_of_choice"),
    ("telegram", Obs(True, "kal bataunga", "free_text"), "free_text_instead_of_choice"),
    ("voice", Obs(True, "7", "keypad", attempts=2), "keypad_out_of_range"),
    ("voice", Obs(True, "हम्म", "speech", attempts=2), "speech_not_understood"),
])
def test_invalid_farmer_input_is_an_outcome_not_an_error(channel, obs, code):
    r = build(channel=channel, items={"q3": obs})
    rule = outcomes.failure_rule(code)
    assert (r["status"], r["failure_code"]) == ("invalid_input", code)
    assert (r["retry_decision"], r["retry_after_minutes"]) == (rule.retry_decision, rule.retry_after_minutes)
    assert r["items"][2]["result"] == "invalid" and r["items"][2]["value"] is None


def test_voice_keypad_and_speech_map_to_options():
    item = POTATO["items"][1]
    assert interpret(SID, item, "3", "keypad") == "spreading"  # 1-based option order
    assert interpret(SID, POTATO["items"][0], " नहीं ", "speech") == "no"
    assert interpret(SID, POTATO["items"][2], "4", "keypad") == 4


# ---- server/channel outcomes -------------------------------------------------
def test_identity_mismatch_is_derived_and_not_stored():
    r = build(channel="telegram", items={"q1": Obs(True, f"mel|{SID}|q1|yes", "callback_data")},
              answered_by="F-SOMEONE-ELSE")
    assert (r["status"], r["failure_code"], r["answers"]) == ("identity_mismatch", "identity_mismatch", {})
    assert r["farmer_id"] == POTATO["farmer_id"] and r["answered_by"] == "F-SOMEONE-ELSE"
    assert r["farmerchat_reply"] is None and r["counts_toward_cap"] is False


def test_duplicate_reply_and_cap():
    r = build(items={"q3": tap(5)}, event="duplicate_answer")
    assert r["farmerchat_reply"] == {"http_status": 200, "outcome": "duplicate"}
    assert r["counts_toward_cap"] is False


def test_delivery_failure_falls_back_without_counting():
    ts = {"sent": TS["sent"], "delivered": None, "opened": None, "answered": None}
    r = build(channel="voice", ts=ts, answered_by=None, event="voice_no_answer")
    assert (r["status"], r["retry_decision"], r["counts_toward_cap"]) == \
        ("delivery_failed", "fall_back_to_next_channel", False)
    assert r["sheet_outcome"] is None


def test_provenance_comes_from_survey():
    r = build(items={"q1": tap("yes"), "q2": tap("no_new"), "q3": tap(5)})
    assert (r["survey_id"], r["farmer_id"], r["source_insight_ids"], r["language"]) == \
        (POTATO["survey_id"], POTATO["farmer_id"], POTATO["source_insight_ids"], POTATO["language"])


# ---- invalid PROGRAM input -> ResponseConfigError ----------------------------
@pytest.mark.parametrize("kwargs, match", [
    ({"items": {"q9": tap("yes")}}, "not in survey"),
    ({"channel": "whatsapp", "items": {"q1": tap("yes")}}, "cannot return input_kind"),
    ({"items": {"q1": tap("maybe")}}, "not an option"),
    ({"items": {"q3": tap(9)}}, "not on the q3 scale"),
    ({"channel": "whatsapp", "items": {"q1": Obs(True, "S-99999|q1|yes", "button_reply")}}, "is for S-99999"),
    ({"channel": "voice", "event": "survey_closed"}, "cannot happen on voice"),
    ({"channel": "whatsapp", "event": "sheet_closed_partway"}, "cannot happen on whatsapp"),
    ({"event": "not_a_code"}, "unknown event"),
    ({"event": "identity_mismatch"}, "derived from the observations"),
    ({"channel": "voice", "event": "keypad_out_of_range"}, "derived from the observations"),
    ({"items": {"q1": Obs(False, raw_input="yes", input_kind="sheet_tap")}}, "not shown"),
    ({"items": {}}, "no accepted answers"),
    ({"items": {"q1": Obs(True, f"{SID}|q1|yes", "button_reply")}, "event": "window_expired",
      "channel": "whatsapp"}, "nothing was answered"),
    ({"channel": "telegram", "ts": TS, "items": {"q1": Obs(True, f"mel|{SID}|q1|yes", "callback_data")}}, "read receipts"),
    ({"channel": "fax"}, "unknown channel"),
    ({"answered_by": "F-OTHER", "event": "duplicate_answer", "items": {"q3": tap(5)}}, "identity_mismatch"),
])
def test_program_errors_raise(kwargs, match):
    with pytest.raises(ResponseConfigError, match=match):
        build(**kwargs)


# ---- simulator ---------------------------------------------------------------
@pytest.mark.parametrize("survey", [POTATO, COW], ids=["potato-scale", "cow-confirm"])
def test_every_allowed_simulated_case_follows_the_rules(survey):
    built = 0
    for channel in outcomes.CHANNELS:
        for case in CASES:
            try:
                r = simulate(survey, channel, case, sent_at=datetime(2026, 12, 6, 9, 0),
                             expires_at=datetime(2026, 12, 11, 19, 0))
            except ResponseConfigError:
                continue  # the rules or channel forbid this pairing
            built += 1
            assert validate("response", r) == []
            assert r["response_key"].startswith("sim-")
            if case in outcomes.failure_codes():
                rule = outcomes.failure_rule(case)
                assert (r["status"], r["failure_code"]) == (rule.status, case)
            if case == "negative_outcome":
                assert r["needs_follow_up"] is True
            if case == "completed":
                assert r["status"] == "completed" and r["complete"] is True
            if case == "identity_mismatch":
                assert r["answered_by"] == SIMULATED_OTHER_FARMER
    assert built >= 61  # at least every combination the official grid covers


def test_simulator_rejects_unscripted_case():
    with pytest.raises(ResponseConfigError):
        simulate(POTATO, "app", "made_up", sent_at=datetime(2026, 12, 6, 9, 0))


# ---- feedback demo -------------------------------------------------------------
def test_feedback_demo_runs_offline_and_validates():
    proc = subprocess.run([sys.executable, "-m", "farmerloop.feedback_demo"],
                          capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr
    assert "all valid against response.schema.json" in proc.stdout
    assert "provenance checked" in proc.stdout
    assert "fall_back_to_next_channel" in proc.stdout
