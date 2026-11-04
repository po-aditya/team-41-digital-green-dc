"""Smoke test: load all golden cases and all practice insights, reporting
successful parses, load failures, and schema-validation failures separately.
Run: .venv/bin/python scripts/smoke_load.py
"""

from __future__ import annotations

import json

from farmerloop import config
from farmerloop.dataio import iter_golden_resilient, iter_insights_resilient
from farmerloop.evaluate import evaluate_eligibility, format_report
from farmerloop.validate import validate


def smoke_golden() -> None:
    parsed = load_fail = schema_fail = 0
    for r in iter_golden_resilient():
        if r.error is not None:
            load_fail += 1
            continue
        parsed += 1
        if validate("insight", r.value.raw_insight):
            schema_fail += 1
    total = parsed + load_fail
    print(f"GOLDEN SET ({config.GOLDEN_JSONL.name})")
    print(f"  rows total              : {total}")
    print(f"  parsed OK               : {parsed}")
    print(f"  load failures           : {load_fail}")
    print(f"  schema-invalid insights : {schema_fail}")
    print()


def smoke_insights() -> None:
    parsed = load_fail = 0
    junk = clean = 0
    for r in iter_insights_resilient():
        if r.error is not None:
            load_fail += 1  # quarantined: ingestion failure, not a decision
            continue
        parsed += 1
        if r.value.quality_flag == "junk":
            junk += 1
        elif r.value.quality_flag == "clean":
            clean += 1

    # Schema validation runs on the ORIGINAL JSON of every row, not on the
    # re-serialized Pydantic model (which can coerce or fill fields and hide
    # violations), and covers rows that failed to load.
    rows = schema_fail = 0
    with config.INSIGHTS_JSONL.open(encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            rows += 1
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                schema_fail += 1
                continue
            if validate("insight", obj):
                schema_fail += 1

    total = parsed + load_fail
    print(f"PRACTICE INSIGHTS ({config.INSIGHTS_JSONL.name})")
    print(f"  rows total              : {total}")
    print(f"  parsed OK               : {parsed}")
    print(f"  load failures           : {load_fail} (quarantined, not no-survey decisions)")
    print(f"  schema-invalid (raw)    : {schema_fail} of {rows} rows")
    print(f"  quality_flag clean/junk : {clean}/{junk} (parsed rows only)")
    print()


def main() -> None:
    smoke_golden()
    smoke_insights()
    report = evaluate_eligibility()
    print(format_report(report))


if __name__ == "__main__":
    main()
