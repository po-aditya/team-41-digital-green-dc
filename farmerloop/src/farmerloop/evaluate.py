"""Golden-set evaluation for the eligibility decision.

Accuracy is reported over EVERY golden row. Load failures are counted and
treated as errors (never excluded), so accuracy cannot be inflated by dropping
rows that failed to parse.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .dataio import GoldenCase, load_golden
from .decide import decide
from .validate import validate


@dataclass
class CaseResult:
    golden_id: str
    insight_id: str
    expected_survey: bool
    predicted_survey: bool
    expected_rule: str | None
    predicted_rule: str
    expected_reason_code: str | None
    predicted_internal_reason: str
    correct: bool
    schema_ok: bool


@dataclass
class EvalReport:
    total_rows: int = 0
    load_errors: int = 0
    scored: int = 0
    correct: int = 0
    schema_failures: int = 0
    results: list[CaseResult] = field(default_factory=list)
    mismatches: list[CaseResult] = field(default_factory=list)
    load_error_detail: list[str] = field(default_factory=list)

    @property
    def accuracy(self) -> float:
        """Accuracy over the TOTAL rows (load errors count against us)."""
        return self.correct / self.total_rows if self.total_rows else 0.0

    @property
    def accuracy_over_scored(self) -> float:
        return self.correct / self.scored if self.scored else 0.0


def _schema_ok_for(case: GoldenCase) -> bool:
    return not validate("insight", case.raw_insight)


def evaluate_eligibility() -> EvalReport:
    load = load_golden()
    report = EvalReport(total_rows=load.total, load_errors=len(load.errors))
    report.load_error_detail = [
        f"line {e.line_no}: {e.error}" for e in load.errors
    ]

    for case in load.cases:
        schema_ok = _schema_ok_for(case)
        if not schema_ok:
            report.schema_failures += 1

        decision = decide(case.insight, schema_ok=schema_ok)
        correct = decision.survey == case.expected_survey

        res = CaseResult(
            golden_id=case.golden_id,
            insight_id=case.insight_id,
            expected_survey=case.expected_survey,
            predicted_survey=decision.survey,
            expected_rule=case.expected_rule,
            predicted_rule=decision.rule,
            expected_reason_code=case.expected_reason_code,
            predicted_internal_reason=decision.internal_reason_code,
            correct=correct,
            schema_ok=schema_ok,
        )
        report.results.append(res)
        report.scored += 1
        if correct:
            report.correct += 1
        else:
            report.mismatches.append(res)

    return report


def format_report(report: EvalReport) -> str:
    lines: list[str] = []
    lines.append("=" * 64)
    lines.append("GOLDEN-SET ELIGIBILITY EVALUATION")
    lines.append("=" * 64)
    lines.append(f"Total golden rows        : {report.total_rows}")
    lines.append(f"  parsed & scored        : {report.scored}")
    lines.append(f"  load failures          : {report.load_errors}")
    lines.append(f"  schema-invalid insights: {report.schema_failures} "
                 "(scored; treated as junk by R1)")
    lines.append("-" * 64)
    lines.append(f"Correct survey/no-survey : {report.correct}/{report.total_rows}")
    lines.append(f"Accuracy (over all rows) : {report.accuracy:.1%}")
    if report.load_errors:
        lines.append(f"Accuracy (scored only)   : {report.accuracy_over_scored:.1%}")
    lines.append("-" * 64)

    if report.load_error_detail:
        lines.append("LOAD FAILURES:")
        for d in report.load_error_detail:
            lines.append(f"  {d}")
        lines.append("-" * 64)

    if report.mismatches:
        lines.append(f"MISMATCHES ({len(report.mismatches)}):")
        for m in report.mismatches:
            lines.append(
                f"  {m.golden_id} {m.insight_id}: "
                f"expected survey={m.expected_survey} (rule {m.expected_rule}), "
                f"got survey={m.predicted_survey} (rule {m.predicted_rule}, "
                f"{m.predicted_internal_reason})"
            )
    else:
        lines.append("No mismatches.")
    lines.append("=" * 64)
    return "\n".join(lines)
