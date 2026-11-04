import json

import pytest

from farmerloop.config import RULES_JSON
from farmerloop.dataio import load_golden
from farmerloop.decide import decide
from farmerloop.evaluate_timing import check_window, evaluate
from farmerloop.timing import compute_window
from tests.helpers import make_insight


def test_clock_difference_is_not_misreported_as_outside_sending_hours():
    window = {"not_before": "2026-12-06T09:00:00+05:30", "not_after": "2026-12-09T19:00:00+05:30"}
    result = check_window(make_insight(), window, json.loads(RULES_JSON.read_text()))
    assert result["constraints_passed"]
    assert result["matches_rule_clocks"] is False


@pytest.mark.parametrize("start,end,reason", [
    ("2026-12-04T07:00:00+05:30", "2026-12-09T19:00:00+05:30", "after_advice_day"),
    ("2026-12-05T07:00:00+05:30", "2026-12-09T19:00:00+05:30", "after_action_window"),
    ("2026-12-06T07:00:00+05:30", "2026-12-07T19:00:00+05:30", "minimum_width"),
    ("2026-12-06T07:00:00+05:30", "2027-04-01T19:00:00+05:30", "within_season"),
    ("2026-12-06T06:00:00+05:30", "2026-12-09T19:00:00+05:30", "within_send_hours"),
    ("2026-12-06T07:00:00Z", "2026-12-09T19:00:00Z", "non_ist_timestamp"),
    ("bad", "2026-12-09T19:00:00+05:30", "invalid_timestamp"),
])
def test_reference_audit_detects_constraint_violations(start, end, reason):
    result = check_window(make_insight(), {"not_before": start, "not_after": end}, json.loads(RULES_JSON.read_text()))
    assert not result["constraints_passed"]
    assert reason in result["violations"]


@pytest.mark.parametrize("timing,start,end", [
    ("same_day", "2026-12-05", "2026-12-07"),
    ("next_day", "2026-12-05", "2026-12-07"),
    ("seasonal", "2026-12-25", "2027-01-18"),
    ("none", "2026-12-07", "2026-12-13"),
])
def test_documented_timing_policy_instead_of_golden_special_cases(timing, start, end):
    window = compute_window("2026-12-04T09:00:00+05:30", timing, None)
    assert str(window.start) == start
    assert str(window.end) == end


def test_reconciliation_keeps_unschedulable_case_in_denominator_and_worked_examples_match():
    report = evaluate()
    assert report["eligibility"]["total_rows"] == 150
    assert report["eligibility"]["correct"] == 149
    golden = report["golden_timing"]
    assert golden["summary"]["reference_surveys"] == 95
    missing = next(r for r in golden["cases"] if r["case_id"] == "G-0145")
    assert missing["generated_window"] is None
    assert "minimum_width" in missing["reference_check"]["violations"]
    assert report["worked_timing"]["summary"]["exact_matches"] == 5


def test_harvest_stage_or_storage_words_do_not_override_valid_followups():
    cases = load_golden().cases
    controls = [c for c in cases if c.expected_survey and c.insight.asset.growth_stage in ("post_harvest", "harvest", "dormant")]
    assert len(controls) == 9
    assert all(decide(c.insight).survey for c in controls)
    # The ambiguous row remains an explicit disagreement, not a hardcoded ID rule.
    disputed = next(c for c in cases if c.golden_id == "G-0136")
    assert disputed.insight.asset.growth_stage is None
    assert decide(disputed.insight).survey
