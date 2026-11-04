"""Ingestion: verified dataset counts, quarantine, reconciliation, provenance, idempotency."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from mel_agent.data.ingest import Ingestor
from mel_agent.data.pack import PackPaths, pack_paths
from mel_agent.store import Store

NOW = "2026-11-04T10:00:00+05:30"


def test_dataset_counts_match_pack(fresh_store):
    run = fresh_store.latest_ingest_run()["stats"]
    assert run["insights_lines"] == 6999
    assert run["farmers"] == 300
    assert run["crop_calendar_rows"] == 86
    assert run["golden_cases"] == 150 and run["golden_missing_from_dataset"] == 0
    assert run["quality_flag_counts"] == {"clean": 6276, "junk": 723}
    assert run["schema_valid_by_quality_flag"] == {"clean": 6276, "junk": 673}
    assert run["insights_quarantined"] == 50 and run["quarantine_by_reason"] == {"schema_invalid": 50}
    assert run["duplicates"] == 0 and run["unknown_farmers"] == 0
    assert run["csv_reconciliation"]["status"] == "ok" and run["csv_reconciliation"]["mismatched_fields"] == {}
    assert fresh_store.count_insights() == 6999
    assert fresh_store.list_quarantine().total == 50


def test_original_record_and_provenance_preserved(fresh_store, settings):
    row = fresh_store.get_insight("I-000001")
    raw_line = next(l for l in pack_paths(settings).insights_jsonl.open(encoding="utf-8") if '"I-000001"' in l).strip()
    assert row["raw_json"] == raw_line
    assert row["source_file"] == "insights.jsonl" and row["line_no"] == 1
    assert fresh_store.get_farmer("F-000001")["line_no"] == 2  # header is line 1


def test_quarantined_rows_are_kept_but_flagged(fresh_store):
    q = fresh_store.list_quarantine(limit=1).items[0]
    row = fresh_store.get_insight(q["insight_id"])
    assert row["schema_valid"] == 0 and row["quarantine_reason"] == "schema_invalid"
    assert all(r["schema_valid"] == 1 for r in fresh_store.iter_insights(only_valid=True))


def test_ingest_is_idempotent(fresh_store, registry, settings):
    before = fresh_store.latest_ingest_run()["stats"]
    stats = Ingestor(fresh_store, registry, pack_paths(settings)).run("2026-11-05T10:00:00+05:30")
    after = stats.to_dict()
    assert after == before
    assert fresh_store.count_insights() == 6999


def _mini_pack(tmp_path: Path, settings, insights: list[str], farmers_csv: str | None = None, insights_csv: str | None = None) -> PackPaths:
    src = pack_paths(settings)
    root = tmp_path / "pack"
    (root / "data").mkdir(parents=True)
    (root / "json" / "rules").mkdir(parents=True)
    shutil.copytree(src.schemas_dir, root / "json" / "schemas")
    for f in (src.rules_json, src.outcome_codes_json):
        shutil.copy(f, root / "json" / "rules" / f.name)
    shutil.copy(src.crop_calendar_csv, root / "data" / "crop_calendar_bihar_rabi.csv")
    (root / "data" / "farmers.csv").write_text(farmers_csv or src.farmers_csv.read_text(encoding="utf-8"), encoding="utf-8")
    (root / "data" / "insights.jsonl").write_text("\n".join(insights) + "\n", encoding="utf-8")
    if insights_csv is not None:
        (root / "data" / "insights.csv").write_text(insights_csv, encoding="utf-8")
    return PackPaths(root)


def test_synthetic_bad_rows_are_quarantined_with_reasons(tmp_path, settings, registry):
    good = json.loads(next(l for l in pack_paths(settings).insights_jsonl.open(encoding="utf-8") if '"I-000001"' in l))
    dup = dict(good)
    unknown = dict(good, insight_id="I-900001", farmer_id="F-999999")
    bad_ts = dict(good, insight_id="I-900002", created_at="2026-11-01T07:35:00Z")
    bad_ts_valid_pattern = dict(good, insight_id="I-900003", created_at="2026-13-45T07:35:00+05:30")
    lines = [json.dumps(good), json.dumps(dup), json.dumps(unknown), json.dumps(bad_ts), json.dumps(bad_ts_valid_pattern), "{not json", "[1,2]", ""]
    paths = _mini_pack(tmp_path, settings, lines)
    store = Store(":memory:")
    stats = Ingestor(store, registry, paths).run(NOW)
    assert stats.insights_lines == 7  # blank line ignored
    assert stats.insights_stored_valid == 1
    assert stats.quarantine_by_reason == {"duplicate_insight_id": 1, "unknown_farmer": 1, "schema_invalid": 2, "invalid_json": 1, "not_an_object": 1}
    assert stats.csv_reconciliation == {"status": "csv_missing"}
    reasons = {q["reason"] for q in store.list_quarantine().items}
    assert "schema_invalid" in reasons  # bad_ts fails the +05:30 pattern; the impossible date fails the format check
    assert store.get_insight("I-000001")["quarantine_reason"] is None


def test_csv_reconciliation_detects_differences(tmp_path, settings, registry):
    good = json.loads(next(l for l in pack_paths(settings).insights_jsonl.open(encoding="utf-8") if '"I-000001"' in l))
    csv_text = "insight_id,farmer_id,severity\nI-000001,F-000216,high\nI-777777,F-000216,low\n"
    paths = _mini_pack(tmp_path, settings, [json.dumps(good)], insights_csv=csv_text)
    stats = Ingestor(Store(":memory:"), registry, paths).run(NOW)
    rec = stats.csv_reconciliation
    assert rec["status"] == "differences"
    assert rec["csv_ids_missing_in_jsonl"] == 1
    assert rec["mismatched_fields"].get("severity") == 1


def test_bad_farmer_and_calendar_rows_rejected(tmp_path, settings, registry):
    good = json.loads(next(l for l in pack_paths(settings).insights_jsonl.open(encoding="utf-8") if '"I-000001"' in l))
    farmers = "farmer_id,district\nF-000216,Darbhanga\nF-000216,Dup\n,Blank\n"
    paths = _mini_pack(tmp_path, settings, [json.dumps(good)], farmers_csv=farmers)
    (paths.root / "data" / "crop_calendar_bihar_rabi.csv").write_text("crop,growth_stage,start_date,end_date\nwheat,,2026-10-25,2026-12-10\n,x,2026-01-01,2026-01-02\nbad,,2026-02-01,2026-01-01\n")
    stats = Ingestor(Store(":memory:"), registry, paths).run(NOW)
    assert stats.farmers == 1 and stats.farmer_rows_rejected == 2
    assert stats.crop_calendar_rows == 1 and stats.crop_calendar_rejected == 2
