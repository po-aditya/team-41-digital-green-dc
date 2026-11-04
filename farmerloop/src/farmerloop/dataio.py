"""Read-only loaders for the participant-pack data.

Nothing here writes to the pack. JSONL is streamed line by line so we never
hold the whole 6,999-row file in memory unless the caller collects it.

Robustness policy:
- Resilient iterators (``*_resilient``) yield a ``LoadResult`` carrying either a
  parsed value OR a ``LoadError``, so callers can count failures and keep going.
- Strict convenience iterators (``iter_insights``, ``iter_golden``) RAISE on the
  first malformed row. They never silently drop rows, so they cannot hide
  parse failures or inflate downstream accuracy.
- ``load_golden`` returns BOTH the parsed cases and the list of load errors, so
  the evaluator can report over all rows (parsed + failed) and never exclude a
  failed row from its denominator.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Generic, TypeVar

from . import config
from .models import Insight

T = TypeVar("T")


@dataclass
class LoadError:
    """A row that could not be parsed. Carries enough to triage it."""

    line_no: int
    error: str
    raw_line: str  # truncated for safety


@dataclass
class LoadResult(Generic[T]):
    """Either a parsed value or a LoadError, plus the source line number."""

    line_no: int
    value: T | None
    error: LoadError | None

    @property
    def ok(self) -> bool:
        return self.error is None


def _truncate(s: str, n: int = 200) -> str:
    s = s.strip()
    return s if len(s) <= n else s[:n] + "..."


def iter_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    """Yield each JSON object from a .jsonl file (assumes valid JSON)."""
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                yield json.loads(line)


# --------------------------------------------------------------------------
# Resilient parsing.
# --------------------------------------------------------------------------
def iter_insights_resilient(
    path: Path | None = None,
) -> Iterator[LoadResult[Insight]]:
    """Stream insights, recording per-row failures instead of raising."""
    path = path or config.INSIGHTS_JSONL
    with path.open(encoding="utf-8") as fh:
        for i, line in enumerate(fh, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                raw = json.loads(stripped)
                insight = Insight.model_validate(raw)
                yield LoadResult(line_no=i, value=insight, error=None)
            except Exception as exc:  # json or pydantic error - keep going.
                err = LoadError(line_no=i, error=f"{type(exc).__name__}: {exc}",
                                raw_line=_truncate(stripped))
                yield LoadResult(line_no=i, value=None, error=err)


def iter_insights(path: Path | None = None) -> Iterator[Insight]:
    """Stream insights, RAISING on the first malformed row.

    Strict by design: use ``iter_insights_resilient`` when you need to survive
    and count failures (e.g. the full practice data).
    """
    for result in iter_insights_resilient(path):
        if result.error is not None:
            raise ValueError(
                f"malformed insight at line {result.line_no}: {result.error.error}"
            )
        assert result.value is not None
        yield result.value


# --------------------------------------------------------------------------
# Golden set.
# --------------------------------------------------------------------------
@dataclass
class GoldenCase:
    """One golden-set row: the raw insight plus the expected decision.

    The golden set carries ``insight_id`` at the TOP level (always identical to
    ``insight.insight_id``); we read the top-level one and fall back to the
    nested value defensively.
    """

    golden_id: str
    insight_id: str
    insight: Insight
    expected: dict[str, Any]
    raw_insight: dict[str, Any]

    @property
    def expected_survey(self) -> bool:
        return bool(self.expected.get("survey"))

    @property
    def expected_rule(self) -> str | None:
        return self.expected.get("rule")

    @property
    def expected_reason_code(self) -> str | None:
        return self.expected.get("reason_code")


def _golden_from_raw(raw: dict[str, Any]) -> GoldenCase:
    insight_raw = raw.get("insight") or {}
    top_id = raw.get("insight_id") or insight_raw.get("insight_id")
    return GoldenCase(
        golden_id=raw.get("golden_id", "?"),
        insight_id=top_id,
        insight=Insight.model_validate(insight_raw),
        expected=raw.get("expected") or {},
        raw_insight=insight_raw,
    )


def iter_golden_resilient(
    path: Path | None = None,
) -> Iterator[LoadResult[GoldenCase]]:
    """Stream golden cases, recording per-row failures instead of raising."""
    path = path or config.GOLDEN_JSONL
    with path.open(encoding="utf-8") as fh:
        for i, line in enumerate(fh, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                raw = json.loads(stripped)
                yield LoadResult(line_no=i, value=_golden_from_raw(raw), error=None)
            except Exception as exc:
                err = LoadError(line_no=i, error=f"{type(exc).__name__}: {exc}",
                                raw_line=_truncate(stripped))
                yield LoadResult(line_no=i, value=None, error=err)


def iter_golden(path: Path | None = None) -> Iterator[GoldenCase]:
    """Stream golden cases, RAISING on the first malformed row."""
    for result in iter_golden_resilient(path):
        if result.error is not None:
            raise ValueError(
                f"malformed golden row at line {result.line_no}: {result.error.error}"
            )
        assert result.value is not None
        yield result.value


@dataclass
class GoldenLoad:
    """All golden rows accounted for: parsed cases AND load failures.

    ``total`` is cases + errors, so an evaluator can divide by the true row
    count and never inflate accuracy by excluding failed rows.
    """

    cases: list[GoldenCase] = field(default_factory=list)
    errors: list[LoadError] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.cases) + len(self.errors)


def load_golden(path: Path | None = None) -> GoldenLoad:
    """Load every golden row, returning parsed cases and load errors together."""
    load = GoldenLoad()
    for result in iter_golden_resilient(path):
        if result.value is not None:
            load.cases.append(result.value)
        elif result.error is not None:
            load.errors.append(result.error)
    return load
