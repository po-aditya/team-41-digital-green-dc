"""Deterministic ingestion of the participant-pack datasets into the store.

Rules
- The pack is read only. Every record is stored verbatim (``raw_json``) with its
  source file and line number.
- A JSONL line that is not valid JSON, not an object, fails insight.schema.json,
  repeats an insight_id, or names an unknown farmer is quarantined. Quarantined
  rows are kept (for reports) but never reach eligibility.
- ``quality_flag`` is stored for diagnostics only. It never influences a decision.
- insights.csv is reconciled against insights.jsonl field by field (nested keys
  flattened with dots, nulls as empty cells). Differences are counted, not fatal.
- Ingestion is idempotent: re-running upserts the same rows and yields the same statistics.
- Ingestion is ATOMIC (review-3 finding 2): every step runs in one database transaction
  together with the run record. A failure anywhere rolls the whole import back, so the
  previously completed dataset stays active and untouched; the failed run is then recorded
  in its own transaction. Runs are ordered by execution sequence, never by the simulated
  ``now`` they were given, and every run has a fresh unique id.
"""

from __future__ import annotations

import csv
import hashlib
import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from mel_agent.contracts import SchemaName, SchemaRegistry
from mel_agent.data.pack import PackPaths
from mel_agent.store import Store
from mel_agent.time_utils import TimeFormatError, parse_ist


class IngestError(RuntimeError):
    pass


@dataclass
class IngestStats:
    insights_lines: int = 0
    insights_stored_valid: int = 0
    insights_quarantined: int = 0
    quarantine_by_reason: dict[str, int] = field(default_factory=dict)
    quality_flag_counts: dict[str, int] = field(default_factory=dict)
    schema_valid_by_quality_flag: dict[str, int] = field(default_factory=dict)
    duplicates: int = 0
    unknown_farmers: int = 0
    csv_rows: int = 0
    csv_reconciliation: dict[str, Any] = field(default_factory=dict)
    farmers: int = 0
    farmer_rows_rejected: int = 0
    crop_calendar_rows: int = 0
    crop_calendar_rejected: int = 0
    golden_cases: int = 0
    golden_missing_from_dataset: int = 0
    content_fingerprint: str = ""

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


def _flatten(obj: Any, prefix: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.update(_flatten(v, f"{prefix}{k}."))
    else:
        out[prefix[:-1]] = obj
    return out


def _csv_equal(json_value: Any, csv_value: str) -> bool:
    if json_value is None:
        return csv_value == ""
    if isinstance(json_value, bool):
        return csv_value.lower() in ({"true", "1"} if json_value else {"false", "0"})
    if isinstance(json_value, (int, float)):
        try:
            return float(csv_value) == float(json_value)
        except ValueError:
            return False
    return str(json_value) == csv_value


def _content_hash(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:16]


class Ingestor:
    def __init__(self, store: Store, registry: SchemaRegistry, paths: PackPaths) -> None:
        self.store = store
        self.registry = registry
        self.paths = paths.require()

    # ---------- farmers ----------

    def ingest_farmers(self, conn, now: str, stats: IngestStats) -> set[str]:
        ids: set[str] = set()
        with self.paths.farmers_csv.open(encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            for line_no, row in enumerate(reader, start=2):
                farmer_id = (row.get("farmer_id") or "").strip()
                if not farmer_id or farmer_id in ids:
                    stats.farmer_rows_rejected += 1
                    continue
                ids.add(farmer_id)
                self.store.upsert_farmer(conn, {
                    "farmer_id": farmer_id, "district": row.get("district"), "language": row.get("language"),
                    "preferred_channel": row.get("preferred_channel"), "raw_json": json.dumps(row, ensure_ascii=False, sort_keys=True),
                    "source_file": self.paths.farmers_csv.name, "line_no": line_no,
                })
        stats.farmers = len(ids)
        return ids

    # ---------- crop calendar ----------

    def ingest_calendar(self, conn, stats: IngestStats) -> None:
        with self.paths.crop_calendar_csv.open(encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            for line_no, row in enumerate(reader, start=2):
                crop = (row.get("crop") or "").strip()
                start, end = row.get("start_date") or "", row.get("end_date") or ""
                try:
                    if not crop or len(start) != 10 or len(end) != 10 or start > end:
                        raise ValueError("bad row")
                    # Validate dates by round-tripping.
                    from datetime import date
                    date.fromisoformat(start); date.fromisoformat(end)
                except ValueError:
                    stats.crop_calendar_rejected += 1
                    continue
                self.store.upsert_calendar(conn, {
                    "calendar_id": f"{self.paths.crop_calendar_csv.name}:{line_no}", "crop": crop,
                    "growth_stage": (row.get("growth_stage") or None), "start_date": start, "end_date": end,
                    "raw_json": json.dumps(row, ensure_ascii=False, sort_keys=True), "line_no": line_no,
                })
                stats.crop_calendar_rows += 1

    # ---------- insights ----------

    def _derived_columns(self, obj: dict[str, Any]) -> dict[str, Any]:
        asset = obj.get("asset") if isinstance(obj.get("asset"), dict) else {}
        return {
            "farmer_id": obj.get("farmer_id") if isinstance(obj.get("farmer_id"), str) else None,
            "created_at": obj.get("created_at") if isinstance(obj.get("created_at"), str) else None,
            "conversation_language": obj.get("conversation_language") if isinstance(obj.get("conversation_language"), str) else None,
            "resolution_type": obj.get("resolution_type") if isinstance(obj.get("resolution_type"), str) else None,
            "asset_name": asset.get("name") if isinstance(asset.get("name"), str) else None,
            "concern": obj.get("concern") if isinstance(obj.get("concern"), str) else None,
            "severity": obj.get("severity") if isinstance(obj.get("severity"), str) else None,
            "quality_flag": obj.get("quality_flag") if isinstance(obj.get("quality_flag"), str) else None,
        }

    def ingest_insights(self, conn, now: str, known_farmers: set[str], stats: IngestStats, run_id: str | None = None) -> dict[str, dict[str, Any]]:
        """Returns {insight_id: parsed object} for schema-valid, non-quarantined rows."""
        validator = self.registry.validator(SchemaName.INSIGHT)
        seen: set[str] = set()
        accepted: dict[str, dict[str, Any]] = {}
        fingerprint = hashlib.sha256()
        src = self.paths.insights_jsonl.name
        with self.paths.insights_jsonl.open(encoding="utf-8") as fh:
            for line_no, line in enumerate(fh, start=1):
                stripped = line.strip()
                if not stripped:
                    continue
                stats.insights_lines += 1
                fingerprint.update(stripped.encode("utf-8"))
                quarantine_reason: str | None = None
                detail: str | None = None
                obj: Any = None
                try:
                    obj = json.loads(stripped)
                except json.JSONDecodeError as exc:
                    quarantine_reason, detail = "invalid_json", f"line {exc.lineno} col {exc.colno}: {exc.msg}"
                if quarantine_reason is None and not isinstance(obj, dict):
                    quarantine_reason, detail = "not_an_object", type(obj).__name__
                insight_id = obj.get("insight_id") if isinstance(obj, dict) else None
                if not isinstance(insight_id, str) or not insight_id:
                    insight_id = None
                schema_valid = False
                if quarantine_reason is None:
                    errors = sorted(validator.iter_errors(obj), key=lambda e: list(e.absolute_path))
                    schema_valid = not errors
                    if errors:
                        first = errors[0]
                        quarantine_reason = "schema_invalid"
                        detail = f"{'/' + '/'.join(str(p) for p in first.absolute_path)}: {first.validator}"
                if quarantine_reason is None:
                    try:
                        parse_ist(obj["created_at"])
                    except TimeFormatError as exc:
                        quarantine_reason, detail = "bad_timestamp", str(exc)
                if quarantine_reason is None and insight_id in seen:
                    quarantine_reason, detail = "duplicate_insight_id", insight_id
                    stats.duplicates += 1
                if quarantine_reason is None and obj["farmer_id"] not in known_farmers:
                    quarantine_reason, detail = "unknown_farmer", obj["farmer_id"]
                    stats.unknown_farmers += 1

                qf_raw = obj.get("quality_flag") if isinstance(obj, dict) else None
                # Diagnostic label only; anything that is not a plain string is counted as such, never used as a key.
                qf = qf_raw if isinstance(qf_raw, str) and qf_raw else ("unlabelled" if qf_raw is None else "invalid_type")
                stats.quality_flag_counts[qf] = stats.quality_flag_counts.get(qf, 0) + 1
                if schema_valid:
                    stats.schema_valid_by_quality_flag[qf] = stats.schema_valid_by_quality_flag.get(qf, 0) + 1

                if insight_id is not None and insight_id not in seen:
                    seen.add(insight_id)
                    derived = self._derived_columns(obj if isinstance(obj, dict) else {})
                    self.store.upsert_insight(conn, {
                        "insight_id": insight_id, **derived, "schema_valid": 1 if schema_valid else 0,
                        "quarantine_reason": quarantine_reason, "source_file": src, "line_no": line_no,
                        "content_hash": _content_hash(obj), "raw_json": stripped, "ingested_at": now, "run_id": run_id,
                    })
                if quarantine_reason is not None:
                    stats.insights_quarantined += 1
                    stats.quarantine_by_reason[quarantine_reason] = stats.quarantine_by_reason.get(quarantine_reason, 0) + 1
                    self.store.add_quarantine(conn, {
                        "quarantine_id": f"{src}:{line_no}", "source_file": src, "line_no": line_no, "insight_id": insight_id,
                        "reason": quarantine_reason, "detail": detail, "raw_text": stripped[:4000], "ingested_at": now,
                    })
                else:
                    accepted[insight_id] = obj
                    stats.insights_stored_valid += 1
        stats.content_fingerprint = fingerprint.hexdigest()[:16]
        return accepted

    # ---------- CSV reconciliation ----------

    def reconcile_csv(self, jsonl_objects: dict[str, dict[str, Any]], stats: IngestStats) -> None:
        if not self.paths.insights_csv.is_file():
            stats.csv_reconciliation = {"status": "csv_missing"}
            return
        by_id_all: dict[str, dict[str, Any]] = {}
        # Compare against every JSON object we could parse, valid or not, so junk rows reconcile too.
        with self.paths.insights_jsonl.open(encoding="utf-8") as fh:
            for line in fh:
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(obj, dict) and isinstance(obj.get("insight_id"), str):
                    by_id_all.setdefault(obj["insight_id"], obj)
        mismatched_fields: dict[str, int] = {}
        missing_in_jsonl = malformed_rows = 0
        csv_ids: set[str] = set()
        with self.paths.insights_csv.open(encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            header = reader.fieldnames or []
            if "insight_id" not in header:
                stats.csv_reconciliation = {"status": "csv_unusable", "detail": "no insight_id column"}
                return
            for row in reader:
                stats.csv_rows += 1
                # Short rows yield None values; long rows collect extras under the restkey (None).
                if any(v is None for k, v in row.items() if k is not None) or None in row:
                    malformed_rows += 1
                    continue
                iid = row.get("insight_id") or ""
                csv_ids.add(iid)
                obj = by_id_all.get(iid)
                if obj is None:
                    missing_in_jsonl += 1
                    continue
                flat = _flatten(obj)
                for col, value in row.items():
                    if col == "insight_id":
                        continue
                    if col in flat and not _csv_equal(flat[col], value):
                        mismatched_fields[col] = mismatched_fields.get(col, 0) + 1
                    elif col not in flat and value != "":
                        mismatched_fields[col] = mismatched_fields.get(col, 0) + 1
        clean = not mismatched_fields and not missing_in_jsonl and not malformed_rows and len(csv_ids) == len(by_id_all)
        stats.csv_reconciliation = {
            "status": "ok" if clean else "differences",
            "csv_rows": stats.csv_rows, "jsonl_objects": len(by_id_all), "csv_ids_missing_in_jsonl": missing_in_jsonl,
            "jsonl_ids_missing_in_csv": len(set(by_id_all) - csv_ids), "malformed_rows": malformed_rows, "mismatched_fields": mismatched_fields,
        }

    # ---------- golden ----------

    def load_golden(self, stats: IngestStats, dataset_ids: Iterable[str]) -> list[dict[str, Any]]:
        ids = set(dataset_ids)
        cases: list[dict[str, Any]] = []
        if not self.paths.golden_jsonl.is_file():
            return cases
        with self.paths.golden_jsonl.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                case = json.loads(line)
                cases.append(case)
                if case.get("insight_id") not in ids:
                    stats.golden_missing_from_dataset += 1
        stats.golden_cases = len(cases)
        return cases

    # ---------- orchestration ----------

    def run(self, now: str) -> IngestStats:
        """Run every step inside ONE write transaction with the run record.

        Success commits the data and the 'complete' status together. Any failure rolls everything
        back (the active dataset is untouched) and a 'failed' run is recorded afterwards with the
        error type, never the data. ``now`` is simulated domain time and is stored as provenance
        only; the run id is unique per execution."""
        run_id = f"ingest-{uuid.uuid4()}"
        stats = IngestStats()
        base = {"run_id": run_id, "started_at": now, "source_root": str(self.paths.root)}
        try:
            with self.store.write() as conn:
                self.store.record_ingest_run({**base, "finished_at": None, "status": "running", "stats": {}}, conn)
                farmers = self.ingest_farmers(conn, now, stats)
                self.ingest_calendar(conn, stats)
                accepted = self.ingest_insights(conn, now, farmers, stats, run_id)
                self.reconcile_csv(accepted, stats)
                self.load_golden(stats, {r[0] for r in conn.execute("SELECT insight_id FROM insights")})
                self.store.record_ingest_run({**base, "finished_at": now, "status": "complete", "stats": stats.to_dict()}, conn)
        except Exception as exc:
            self.store.record_ingest_run({**base, "finished_at": now, "status": "failed", "error": type(exc).__name__, "stats": stats.to_dict()})
            raise IngestError(f"ingestion failed ({type(exc).__name__}); run marked failed and rolled back") from exc
        return stats

    def store_all_ids(self) -> set[str]:
        with self.store.read() as conn:
            return {r[0] for r in conn.execute("SELECT insight_id FROM insights")}
