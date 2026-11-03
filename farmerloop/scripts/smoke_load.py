"""Smoke test: load all golden cases and all practice insights, reporting
successful parses, load failures, and schema-validation failures separately.
Run: .venv/bin/python scripts/smoke_load.py
"""

from __future__ import annotations

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
    parsed = load_fail = schema_fail = 0
    junk = clean = 0
    for r in iter_insights_resilient():
        if r.error is not None:
            load_fail += 1
            continue
        parsed += 1
        ins = r.value
        if ins.quality_flag == "junk":
            junk += 1
        elif ins.quality_flag == "clean":
            clean += 1
        if validate("insight", ins.raw):
            schema_fail += 1
    total = parsed + load_fail
    print(f"PRACTICE INSIGHTS ({config.INSIGHTS_JSONL.name})")
    print(f"  rows total              : {total}")
    print(f"  parsed OK               : {parsed}")
    print(f"  load failures           : {load_fail}")
    print(f"  schema-invalid insights : {schema_fail}")
    print(f"  quality_flag clean/junk : {clean}/{junk}")
    print()


def main() -> None:
    smoke_golden()
    smoke_insights()
    report = evaluate_eligibility()
    print(format_report(report))


if __name__ == "__main__":
    main()
