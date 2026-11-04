"""Golden-set baseline for the eligibility decision.

Locks in the current accuracy and the known R7 limitation so a regression is
caught. Reports over EVERY golden row (load failures count against accuracy).
"""

from farmerloop.evaluate import evaluate_eligibility

# Current measured baseline. Raise this if the logic improves; a drop is a
# regression. The single known miss is G-0136 (R7, see docs/DECISIONS.md).
BASELINE_CORRECT = 149
TOTAL_ROWS = 150


def test_golden_eligibility_baseline():
    report = evaluate_eligibility()
    assert report.total_rows == TOTAL_ROWS
    assert report.load_errors == 0
    assert report.correct >= BASELINE_CORRECT, (
        f"eligibility regressed: {report.correct}/{report.total_rows}; "
        f"mismatches={[m.golden_id for m in report.mismatches]}"
    )


def test_only_known_mismatch_is_r7():
    report = evaluate_eligibility()
    unexpected = [m.golden_id for m in report.mismatches if m.golden_id != "G-0136"]
    assert not unexpected, f"unexpected mismatches beyond known R7 case: {unexpected}"


def test_accuracy_counts_all_rows_not_just_scored():
    report = evaluate_eligibility()
    # Denominator is total rows, never the scored subset.
    assert report.accuracy == report.correct / report.total_rows
