"""Eligibility rules: precedence, each rule, quality_flag independence, golden agreement."""

from __future__ import annotations

import copy
import inspect
import json
import re

import pytest

import mel_agent.rules.eligibility as elig
from mel_agent.rules.eligibility import CropCalendar, Outcome, Reason, decide, is_junk


@pytest.fixture
def base(load_example):
    return load_example("scenarios/1-mustard-aphid-spray/insight.json")


def test_worked_scenarios(scenario_dirs, rules, calendar):
    for d in scenario_dirs:
        insight = json.loads((d / "insight.json").read_text())
        decision = decide(insight, rules, calendar)
        if (d / "no_survey.json").exists():
            expected = json.loads((d / "no_survey.json").read_text())
            assert decision.outcome is Outcome.NO_SURVEY
            assert decision.to_no_survey_contract()["reason_code"] == expected["reason_code"]
        else:
            assert decision.survey, d.name


def test_precedence_order(base, rules, calendar):
    # R0 before everything
    assert decide(base, rules, calendar, schema_valid=False).reason is Reason.SCHEMA_INVALID
    assert decide(base, rules, calendar, farmer_known=False).reason is Reason.UNKNOWN_FARMER
    # R2 critical beats R1 junk: a contradictory record goes to a human, never silently to the bin (Codex H7)
    junk_critical = dict(base, decision_episode_type="casual", severity="critical")
    d = decide(junk_critical, rules, calendar)
    assert d.reason is Reason.CRITICAL_NEEDS_HUMAN_CALL and d.needs_human and d.details["contradictory_signals"] == "casual_episode"
    # R2 critical beats R3/R4/R5
    crit = dict(base, severity="critical", resolution_type="needs_more_context")
    d = decide(crit, rules, calendar)
    assert d.reason is Reason.CRITICAL_NEEDS_HUMAN_CALL and d.needs_human and d.rule == "R2"
    # R3 / R4
    assert decide(dict(base, resolution_type="generic_information"), rules, calendar).reason is Reason.NOTHING_TO_VERIFY
    assert decide(dict(base, resolution_type="needs_more_context"), rules, calendar).reason is Reason.WAITING_FOR_DETAILS
    # R5
    assert decide(dict(base, verification={"needed": False, "timing": "none", "method": "none"}), rules, calendar).reason is Reason.NO_CHECK_NEEDED
    # R6
    late = dict(base, created_at="2027-03-30T10:00:00+05:30")
    d = decide(late, rules, calendar)
    assert d.reason is Reason.WINDOW_AFTER_SEASON and d.details["season_end"] == "2027-03-31"
    # R7: cauliflower calendar ends 2027-03-20; window from 2027-03-16 + 5 days starts after it
    cf = dict(base, created_at="2027-03-16T10:00:00+05:30", asset={"name": "cauliflower", "category": "crop", "growth_stage": None}, action_window_days=5)
    d = decide(cf, rules, calendar)
    assert d.reason is Reason.CROP_ALREADY_HARVESTED and d.details["crop_calendar_end"] == "2027-03-20"
    # R8
    assert decide(base, rules, calendar).reason is Reason.SURVEY


def test_unknown_resolution_is_quarantined(base, rules, calendar):
    d = decide(dict(base, resolution_type="indirect_action"), rules, calendar)
    assert d.outcome is Outcome.QUARANTINED and d.reason is Reason.UNKNOWN_RESOLUTION


def test_quality_flag_never_changes_a_decision(golden_cases, rules, calendar):
    for case in golden_cases:
        a = copy.deepcopy(case["insight"])
        b = copy.deepcopy(case["insight"])
        a["quality_flag"], b["quality_flag"] = "clean", "junk"
        da, db = decide(a, rules, calendar), decide(b, rules, calendar)
        assert (da.outcome, da.reason) == (db.outcome, db.reason), case["insight_id"]
        a.pop("quality_flag")
        assert decide(a, rules, calendar).reason is da.reason


def test_no_hard_coded_insight_ids_or_golden_labels_in_rules():
    src = inspect.getsource(elig)
    assert not re.search(r"I-\d{6}", src)
    # The rules module never opens the golden file or imports anything that does.
    assert "golden_set" not in src and "golden.jsonl" not in src and "golden_jsonl" not in src
    assert not re.search(r"^\s*(from|import)\s+mel_agent\.evaluation", src, re.M)
    code_only = re.sub(r'"""(.|\n)*?"""', "", src)  # drop docstrings, which explain the policy
    code_only = re.sub(r"#.*", "", code_only)      # and comments
    assert "quality_flag" not in code_only


def test_junk_signature_on_golden_and_dataset(golden_cases, settings):
    from mel_agent.data.pack import pack_paths

    for case in golden_cases:
        expect_junk = case["expected"].get("reason_code") == "junk_insight"
        assert is_junk(case["insight"])[0] == expect_junk, case["insight_id"]
    # Diagnostic property of this dataset: the signature separates every labelled junk row from every clean row.
    junk = clean = fp = fn = 0
    for line in pack_paths(settings).insights_jsonl.open(encoding="utf-8"):
        obj = json.loads(line)
        flagged, _ = is_junk(obj)
        if obj.get("quality_flag") == "junk":
            junk += 1; fn += not flagged
        else:
            clean += 1; fp += flagged
    assert (junk, clean) == (723, 6276)
    assert fp == 0 and fn == 0


def test_external_reason_codes_respect_no_survey_schema(golden_cases, rules, calendar, registry):
    for case in golden_cases:
        d = decide(case["insight"], rules, calendar)
        if d.outcome is Outcome.NO_SURVEY:
            doc = d.to_no_survey_contract()
            assert not registry.errors("no_survey", doc)
            assert doc["reason_code"] in ("generic_information", "needs_more_context")
            assert d.reason.value in doc["reason"]  # internal reason still visible to reviewers
        else:
            with pytest.raises(ValueError):
                d.to_no_survey_contract()


def test_golden_agreement_floor(golden_cases, rules, calendar):
    agree = sum(decide(c["insight"], rules, calendar).survey == bool(c["expected"]["survey"]) for c in golden_cases)
    assert agree >= 148  # measured 149/150; the one known miss is the timing-contract disagreement


def test_crop_calendar_lookup():
    cal = CropCalendar.from_rows([{"crop": "Wheat", "end_date": "2027-04-25"}, {"crop": "wheat", "end_date": "2027-03-01"}])
    assert cal.last_date("wheat").isoformat() == "2027-04-25"
    assert cal.last_date("rice") is None and cal.last_date(None) is None
