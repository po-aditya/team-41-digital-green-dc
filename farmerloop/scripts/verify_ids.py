"""Verify deterministic IDs are collision-free across all practice insights.

Strict contract (no silent skipping, no pre-dedup hiding problems):
  * The file MUST contain exactly EXPECTED_ROWS data rows.
  * Every row MUST carry a non-empty, pattern-valid insight_id.
  * The source insight_ids MUST already be unique (duplicates are a hard fail,
    reported BEFORE any generation).
Only once the source is proven clean do we generate and check survey_id,
handoff_id, flow_key and flow_id for uniqueness and schema-pattern validity.

Run: .venv/bin/python scripts/verify_ids.py
"""

from __future__ import annotations

import json
import re
from collections import Counter

from farmerloop import config, ids

EXPECTED_ROWS = 6999
_INSIGHT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


def collect_insight_ids() -> list[str]:
    """Return the insight_id of every data row, in file order.

    Raises on a row with missing/blank/invalid insight_id - we do NOT skip.
    A bad JSON line is also a hard failure here (the practice file's 50
    quarantined rows are still valid JSON objects; they only fail the richer
    insight schema, not json.loads, so they still carry an insight_id).
    """
    ids_in_order: list[str] = []
    bad: list[str] = []
    with config.INSIGHTS_JSONL.open(encoding="utf-8") as fh:
        for i, line in enumerate(fh, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as exc:
                bad.append(f"line {i}: invalid JSON ({exc})")
                continue
            iid = obj.get("insight_id")
            if not isinstance(iid, str) or not _INSIGHT_ID_RE.match(iid):
                bad.append(f"line {i}: missing/invalid insight_id {iid!r}")
                continue
            ids_in_order.append(iid)
    if bad:
        print("SOURCE INSIGHT-ID FAILURES:")
        for b in bad[:20]:
            print(f"  {b}")
        raise SystemExit(f"FAIL: {len(bad)} rows with missing/invalid insight_id")
    return ids_in_order


def report_dups(name: str, values: list[str]) -> bool:
    counts = Counter(values)
    dups = {v: c for v, c in counts.items() if c > 1}
    print(f"  {name:12s}: {len(values)} generated, {len(counts)} unique, "
          f"{len(dups)} colliding")
    for v, c in list(dups.items())[:5]:
        print(f"      COLLISION {v!r} x{c}")
    return not dups


def main() -> None:
    insight_ids = collect_insight_ids()

    # Hard count check - never pass if the file isn't the expected size.
    print(f"Insight rows read: {len(insight_ids)} (expected {EXPECTED_ROWS})")
    if len(insight_ids) != EXPECTED_ROWS:
        raise SystemExit(
            f"FAIL: expected {EXPECTED_ROWS} insight rows, got {len(insight_ids)}"
        )

    # Source uniqueness BEFORE any dedup - duplicates are a hard failure.
    src_counts = Counter(insight_ids)
    src_dups = {v: c for v, c in src_counts.items() if c > 1}
    print(f"Unique source insight_ids: {len(src_counts)}")
    if src_dups:
        for v, c in list(src_dups.items())[:10]:
            print(f"  DUPLICATE source insight_id {v!r} x{c}")
        raise SystemExit(f"FAIL: {len(src_dups)} duplicate source insight_ids")

    # Generate over EVERY row (not a dedup set - they are already unique).
    survey_ids = [ids.survey_id(i) for i in insight_ids]
    handoff_ids = [ids.handoff_id(s) for s in survey_ids]
    flow_keys = [ids.flow_key(s) for s in survey_ids]
    flow_ids = [ids.flow_id(s) for s in survey_ids]

    ok = True
    ok &= report_dups("survey_id", survey_ids)
    ok &= report_dups("handoff_id", handoff_ids)
    ok &= report_dups("flow_key", flow_keys)
    ok &= report_dups("flow_id", flow_ids)

    # Schema-pattern validity.
    pat_ok = (
        all(re.fullmatch(r"S-[0-9]{5,10}", s) for s in survey_ids)
        and all(re.fullmatch(r"H-[0-9]{5,10}", h) for h in handoff_ids)
        and all(re.fullmatch(r"[a-z][a-z0-9_]{1,63}", k) for k in flow_keys)
    )
    print(f"  pattern-valid: {pat_ok}")
    ok &= pat_ok

    print("RESULT:", "ALL UNIQUE + PATTERN-VALID" if ok else "COLLISIONS/INVALID FOUND")
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
