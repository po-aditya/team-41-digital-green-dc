"""Audit timing rules separately from exact agreement with pack v1 examples.

No generator, model calls, or reference-driven scheduling. Crop-calendar rows
are context for review, not evidence of an individual farmer's harvest date.
"""

import argparse
from collections import Counter
import csv
from dataclasses import asdict
from datetime import date, datetime, time, timedelta
import json

from . import config
from .dataio import load_golden
from .decide import decide
from .models import Insight
from .timing import compute_window
from .validate import validate


def check_window(insight, window, rules):
    """Independently check the brief's explicit constraints, not agronomic fit.

    Clock *boundaries* (07:00/19:00) are reported separately from staying within
    allowed sending hours. A 09:00 opening is allowed-hour compliant but differs
    from the documented baseline opening clock.
    """
    if window is None:
        return {"available": False, "constraints_passed": False,
                "violations": ["no_feasible_window"], "matches_rule_clocks": None}
    try:
        start = datetime.fromisoformat(window["not_before"])
        end = datetime.fromisoformat(window["not_after"])
        advice = datetime.fromisoformat(insight.created_at).date()
    except (KeyError, TypeError, ValueError):
        return {"available": True, "constraints_passed": False,
                "violations": ["invalid_timestamp"], "matches_rule_clocks": False}
    wr = rules["window_rules"]
    clocks_match = (start.time() == time.fromisoformat(wr["not_before_time"])
                    and end.time() == time.fromisoformat(wr["not_after_time"]))
    if start.utcoffset() != timedelta(hours=5, minutes=30) or end.utcoffset() != timedelta(hours=5, minutes=30):
        return {"available": True, "constraints_passed": False,
                "violations": ["non_ist_timestamp"], "matches_rule_clocks": clocks_match}
    minimum_day = advice + timedelta(days=wr["earliest_start_day"])
    action_end = advice + timedelta(days=insight.action_window_days or 0)
    hours = rules["send_hours"]
    checks = {
        "ordered": end >= start,
        "after_advice_day": start.date() >= minimum_day,
        "after_action_window": not wr["start_not_before_action_window_end"] or start.date() >= action_end,
        "minimum_width": (end.date() - start.date()).days >= wr["min_width_days"],
        "within_season": end.date() <= date.fromisoformat(wr["season_end"]),
        "within_send_hours": all(time.fromisoformat(hours["from"]) <= t.time() <= time.fromisoformat(hours["to"]) for t in (start, end)),
    }
    violations = [name for name, passed in checks.items() if not passed]
    return {"available": True, "constraints_passed": not violations,
            "violations": violations, "matches_rule_clocks": clocks_match}


def compare_windows(insight, reference, rules):
    computed = compute_window(insight.created_at, insight.verification.timing, insight.action_window_days)
    actual = None if computed is None else {
        "not_before": computed.not_before_iso(), "not_after": computed.not_after_iso()}
    reference_check = check_window(insight, reference, rules)
    actual_check = check_window(insight, actual, rules)
    exact = bool(actual is not None and actual == reference)
    dates = bool(actual and reference and
                 all(isinstance(reference.get(k), str) for k in ("not_before", "not_after")) and
                 actual["not_before"][:10] == reference["not_before"][:10] and
                 actual["not_after"][:10] == reference["not_after"][:10])
    return {"generated_window": actual, "reference_window": reference,
            "generated_check": actual_check, "reference_check": reference_check,
            "exact_match": exact, "date_match": dates,
            "difference": "no_feasible_window" if actual is None else
                          "exact" if exact else "clock_only" if dates else "dates_and_or_clocks"}


def _summary(rows):
    return {
        "reference_surveys": len(rows),
        "generated_windows": sum(r["generated_check"]["available"] for r in rows),
        "generated_constraint_passes": sum(r["generated_check"]["constraints_passed"] for r in rows),
        "reference_constraint_passes": sum(r["reference_check"]["constraints_passed"] for r in rows),
        "generated_rule_clock_matches": sum(r["generated_check"]["matches_rule_clocks"] is True for r in rows),
        "reference_rule_clock_matches": sum(r["reference_check"]["matches_rule_clocks"] is True for r in rows),
        "exact_matches": sum(r["exact_match"] for r in rows),
        "date_matches": sum(r["date_match"] for r in rows),
        "differences": dict(Counter(r["difference"] for r in rows)),
        "reference_constraint_violations": dict(Counter(v for r in rows for v in r["reference_check"]["violations"])),
    }


def evaluate():
    rules = json.loads(config.RULES_JSON.read_text())
    load = load_golden()
    rows, mismatches = [], []
    correct = invalid = 0
    with config.CROP_CALENDAR_CSV.open() as fh:
        calendar = list(csv.DictReader(fh))
    for case in load.cases:
        schema_ok = not validate("insight", case.raw_insight)
        invalid += not schema_ok
        decision = decide(case.insight, schema_ok=schema_ok)
        correct += decision.survey == case.expected_survey
        if decision.survey != case.expected_survey:
            mismatches.append({"golden_id": case.golden_id, "insight": case.raw_insight,
                               "expected": case.expected, "decision": asdict(decision),
                               "crop_calendar_context": [r for r in calendar if r["crop"] == case.insight.asset.name]})
        if case.expected_survey:
            reference = case.expected.get("send_window", {})
            normalized = {"not_before": reference.get("start"), "not_after": reference.get("end")}
            if not schema_ok:
                raise ValueError(f"Cannot audit timing of schema-invalid golden survey {case.golden_id}")
            rows.append({"case_id": case.golden_id, "insight": case.raw_insight,
                         **compare_windows(case.insight, normalized, rules)})
    worked = []
    for path in sorted((config.PARTICIPANT_PACK / "json/scenarios").glob("*/insight.json")):
        survey_path = path.parent / "survey.en-IN.json"
        if survey_path.exists():
            insight = Insight.model_validate_json(path.read_text())
            reference = json.loads(survey_path.read_text())["send_window"]
            worked.append({"case_id": path.parent.name, **compare_windows(insight, reference, rules)})
    return {
        "label": "Offline pack-v1 timing reconciliation; rule compliance and reference agreement are separate",
        "policy_source": "json/rules/rules.json and index.html: When to send",
        "rules": {k: rules[k] for k in ("send_window_days", "window_rules", "send_hours")},
        "limitations": [
            "No semantic eligibility score or agronomic correctness claim.",
            "Crop calendar is typical regional context, not an individual harvest observation.",
            "A constraint pass does not establish crop-calendar or advice-specific timeliness.",
            "All expected golden surveys remain in the timing denominator, including infeasible windows.",
        ],
        "eligibility": {"total_rows": load.total, "correct": correct,
                        "load_errors": [f"line {e.line_no}: {e.error}" for e in load.errors],
                        "invalid_inputs": invalid, "mismatches": mismatches},
        "golden_timing": {"summary": _summary(rows), "cases": rows},
        "worked_timing": {"summary": _summary(worked), "cases": worked},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report = evaluate()
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(report["label"])
        e = report["eligibility"]
        print(f"Eligibility: {e['correct']}/{e['total_rows']}; load errors: {len(e['load_errors'])}")
        for key in ("golden_timing", "worked_timing"):
            print(key, json.dumps(report[key]["summary"], indent=2))
        print("Use --json for individual comparisons and the unresolved eligibility case.")


if __name__ == "__main__":
    main()
