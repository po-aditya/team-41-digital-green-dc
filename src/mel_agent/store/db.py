"""Durable state in SQLite, written in PostgreSQL-compatible SQL.

Design notes
- stdlib ``sqlite3`` only; no ORM. Portable constructs only: TEXT/INTEGER/REAL,
  ``ON CONFLICT (...) DO UPDATE``, explicit primary keys, ISO-8601 text timestamps.
- One process-wide lock serialises writers; readers open their own connection.
  SQLite WAL mode lets reads proceed during writes.
- Every table stores the full JSON document plus a few indexed columns, so the
  original record is always preserved alongside derived fields.
- All list queries are paginated with a hard upper bound and a stable ORDER BY.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

MAX_PAGE_SIZE = 200
DEFAULT_PAGE_SIZE = 50


class StoreError(RuntimeError):
    pass


@dataclass
class Page:
    items: list[dict[str, Any]]
    total: int
    limit: int
    offset: int

    def to_dict(self) -> dict[str, Any]:
        return {"items": self.items, "total": self.total, "limit": self.limit, "offset": self.offset,
                "next_offset": self.offset + self.limit if self.offset + self.limit < self.total else None}


_SCHEMA = [
    # seq orders runs by execution (monotonic, assigned at insert); started_at is simulated domain time and
    # must never decide which run is current. recorded_at is wall-clock provenance.
    """CREATE TABLE IF NOT EXISTS ingest_runs (
        run_id TEXT PRIMARY KEY, started_at TEXT NOT NULL, finished_at TEXT, source_root TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'running', error TEXT, stats_json TEXT NOT NULL,
        seq INTEGER, recorded_at TEXT)""",
    """CREATE TABLE IF NOT EXISTS generation_claims (
        insight_id TEXT PRIMARY KEY, survey_id TEXT NOT NULL UNIQUE, status TEXT NOT NULL, owner TEXT NOT NULL,
        token TEXT NOT NULL, lease_until REAL NOT NULL, claimed_at TEXT NOT NULL, updated_at TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS insights (
        insight_id TEXT PRIMARY KEY, farmer_id TEXT, created_at TEXT, conversation_language TEXT,
        resolution_type TEXT, asset_name TEXT, concern TEXT, severity TEXT, quality_flag TEXT,
        schema_valid INTEGER NOT NULL, quarantine_reason TEXT, source_file TEXT NOT NULL, line_no INTEGER NOT NULL,
        content_hash TEXT NOT NULL, raw_json TEXT NOT NULL, ingested_at TEXT NOT NULL, run_id TEXT)""",
    "CREATE INDEX IF NOT EXISTS ix_insights_farmer ON insights (farmer_id, created_at)",
    "CREATE INDEX IF NOT EXISTS ix_insights_created ON insights (created_at, insight_id)",
    """CREATE TABLE IF NOT EXISTS quarantine (
        quarantine_id TEXT PRIMARY KEY, source_file TEXT NOT NULL, line_no INTEGER NOT NULL, insight_id TEXT,
        reason TEXT NOT NULL, detail TEXT, raw_text TEXT NOT NULL, ingested_at TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS farmers (
        farmer_id TEXT PRIMARY KEY, district TEXT, language TEXT, preferred_channel TEXT, raw_json TEXT NOT NULL,
        source_file TEXT NOT NULL, line_no INTEGER NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS crop_calendar (
        calendar_id TEXT PRIMARY KEY, crop TEXT NOT NULL, growth_stage TEXT, start_date TEXT NOT NULL,
        end_date TEXT NOT NULL, raw_json TEXT NOT NULL, line_no INTEGER NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS decisions (
        insight_id TEXT PRIMARY KEY, farmer_id TEXT, decision TEXT NOT NULL, rule TEXT NOT NULL,
        internal_reason TEXT NOT NULL, external_reason_code TEXT, reason_text TEXT NOT NULL,
        details_json TEXT NOT NULL, decided_at TEXT NOT NULL, run_id TEXT)""",
    "CREATE INDEX IF NOT EXISTS ix_decisions_decision ON decisions (decision, insight_id)",
    """CREATE TABLE IF NOT EXISTS surveys (
        survey_id TEXT PRIMARY KEY, insight_id TEXT NOT NULL, farmer_id TEXT NOT NULL, language TEXT NOT NULL,
        status TEXT NOT NULL, generation_source TEXT NOT NULL, attempts INTEGER NOT NULL,
        survey_json TEXT, validation_json TEXT NOT NULL, timing_json TEXT NOT NULL, created_at TEXT NOT NULL)""",
    "CREATE INDEX IF NOT EXISTS ix_surveys_farmer ON surveys (farmer_id, survey_id)",
    """CREATE TABLE IF NOT EXISTS handoffs (
        handoff_id TEXT PRIMARY KEY, survey_id TEXT NOT NULL, farmer_id TEXT NOT NULL, priority TEXT NOT NULL,
        not_before TEXT NOT NULL, not_after TEXT NOT NULL, expires_at TEXT NOT NULL, state TEXT NOT NULL,
        state_detail TEXT, counted_at TEXT, handoff_json TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""",
    "CREATE INDEX IF NOT EXISTS ix_handoffs_state ON handoffs (state, not_before, handoff_id)",
    "CREATE INDEX IF NOT EXISTS ix_handoffs_farmer ON handoffs (farmer_id, counted_at)",
    """CREATE TABLE IF NOT EXISTS delivery_attempts (
        attempt_key TEXT PRIMARY KEY, handoff_id TEXT NOT NULL, survey_id TEXT NOT NULL, channel TEXT NOT NULL,
        channel_index INTEGER NOT NULL, delivery_attempt INTEGER NOT NULL, state TEXT NOT NULL,
        scheduled_for TEXT NOT NULL, sent_at TEXT, outcome_status TEXT, failure_code TEXT, response_key TEXT,
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""",
    "CREATE INDEX IF NOT EXISTS ix_attempts_handoff ON delivery_attempts (handoff_id, channel_index, delivery_attempt)",
    """CREATE TABLE IF NOT EXISTS responses (
        response_key TEXT PRIMARY KEY, survey_id TEXT NOT NULL, farmer_id TEXT NOT NULL, channel TEXT NOT NULL,
        status TEXT NOT NULL, failure_code TEXT, needs_follow_up INTEGER NOT NULL, counts_toward_cap INTEGER NOT NULL,
        recorded_at TEXT NOT NULL, record_json TEXT NOT NULL)""",
    "CREATE INDEX IF NOT EXISTS ix_responses_survey ON responses (survey_id, recorded_at)",
    """CREATE TABLE IF NOT EXISTS audit_log (
        seq INTEGER PRIMARY KEY, at TEXT NOT NULL, entity TEXT NOT NULL, entity_id TEXT NOT NULL,
        event TEXT NOT NULL, details_json TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS budget_ledger (
        entry_id TEXT PRIMARY KEY, reservation_id TEXT NOT NULL, created_at TEXT NOT NULL, kind TEXT NOT NULL,
        model_id TEXT NOT NULL, estimated_usd REAL NOT NULL, actual_usd REAL, input_tokens INTEGER,
        output_tokens INTEGER, note TEXT)""",
    "CREATE INDEX IF NOT EXISTS ix_ledger_reservation ON budget_ledger (reservation_id, kind)",
    # One event of each kind per reservation: a second settle/release/unresolved/reconcile row cannot be stored.
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_ledger_reservation_kind ON budget_ledger (reservation_id, kind)",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_ledger_terminal ON budget_ledger (reservation_id) WHERE kind IN ('settle', 'release', 'unresolved')",
    """CREATE TABLE IF NOT EXISTS kv (
        k TEXT PRIMARY KEY, v TEXT NOT NULL)""",
]


# Schema versioning (review-3 finding 6). Version 1: 8bb4569 layout. Version 2: generation claims carry a
# fencing token and a real-time lease; ledger uniqueness indexes. Version 3: ingest runs ordered by seq with
# wall-clock provenance; insights record the run that wrote them. Migrations only ADD columns with defaults
# (existing data is preserved) and run inside the same write transaction as the CREATE statements, so an
# interrupted upgrade leaves the previous version intact and the next startup completes it.
SCHEMA_VERSION = 3
# Versions this build can open. 1 = 8bb4569 layout (kv table present, no marker), 2 = review-2 layout
# (no marker either; distinguished only by columns), 3 = current. Anything else (newer, zero, negative,
# non-numeric) is refused BEFORE any statement touches the database (review-4 finding 4).
SUPPORTED_SCHEMA_VERSIONS = frozenset({1, 2, 3})
_COLUMN_MIGRATIONS: list[tuple[str, str, str]] = [
    # (table, column, DDL type/default) — idempotent: applied only when the column is missing
    ("generation_claims", "token", "TEXT NOT NULL DEFAULT ''"),
    ("generation_claims", "lease_until", "REAL NOT NULL DEFAULT 0"),
    ("ingest_runs", "seq", "INTEGER"),
    ("ingest_runs", "recorded_at", "TEXT"),
    ("insights", "run_id", "TEXT"),
]


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {k: row[k] for k in row.keys()}


class Store:
    """Repository over one SQLite file (or ':memory:' for tests)."""

    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        self._lock = threading.RLock()
        self._memory_conn: sqlite3.Connection | None = None
        self._local = threading.local()  # one long-lived connection per thread for file databases
        if self.path == ":memory:":
            self._memory_conn = self._connect()
        if self.path not in (":memory:",):
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._initialise()

    def _initialise(self) -> None:
        """Create or upgrade the schema atomically. Concurrent starters serialise on BEGIN IMMEDIATE and
        the second one finds nothing left to do. Refuses (StoreError) rather than continuing on a database
        it cannot bring to the supported version."""
        try:
            with self.write() as conn:
                tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
                found = self._stored_version(conn, tables)
                if found is not None and found not in SUPPORTED_SCHEMA_VERSIONS:
                    # Raised inside the transaction before any DDL: rollback leaves contents and marker untouched.
                    raise StoreError(f"unsupported database schema version {found!r} at {self.path}: this build supports versions "
                                     f"{sorted(SUPPORTED_SCHEMA_VERSIONS)} and refuses to migrate, downgrade or overwrite it; nothing was changed. "
                                     "Use a build that supports that version, or point MEL_DATABASE_URL at a different database")
                for table, column, ddl in _COLUMN_MIGRATIONS:
                    if table in tables and column not in self._columns(conn, table):
                        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
                for stmt in _SCHEMA:
                    conn.execute(stmt)
                conn.execute("INSERT INTO kv (k, v) VALUES ('schema_version', ?) ON CONFLICT (k) DO UPDATE SET v = excluded.v", (str(SCHEMA_VERSION),))
        except sqlite3.IntegrityError as exc:
            raise StoreError("database upgrade refused: the budget ledger contains duplicate reservation events, which the current "
                             "version forbids; reconcile the ledger rows manually before starting (nothing was changed)") from exc
        except sqlite3.OperationalError as exc:
            raise StoreError(f"database schema could not be initialised or upgraded: {exc}") from exc

    @staticmethod
    def _stored_version(conn: sqlite3.Connection, tables: set[str]) -> int | str | None:
        """None for an empty (fresh) database; 1 for a legacy layout without a marker; otherwise the marker
        as an int when it is a canonical non-negative integer string, else the raw string (unsupported)."""
        if not tables:
            return None
        if "kv" not in tables:
            return 1
        row = conn.execute("SELECT v FROM kv WHERE k = 'schema_version'").fetchone()
        if row is None:
            return 1
        raw = row[0]
        if isinstance(raw, str) and raw.isdigit() and str(int(raw)) == raw:
            return int(raw)
        return str(raw)

    @staticmethod
    def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
        return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}

    def schema_version(self) -> int:
        v = self.kv_get("schema_version")
        return int(v) if v else 0

    def checkpoint(self) -> None:
        """Flush the WAL into the main file (needed before copying the database file)."""
        if self._memory_conn is None:
            with self._lock:
                self._thread_conn().execute("PRAGMA wal_checkpoint(TRUNCATE)")

    def _thread_conn(self) -> sqlite3.Connection:
        if self._memory_conn is not None:
            return self._memory_conn
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = self._connect()
            self._local.conn = conn
        return conn

    @classmethod
    def from_url(cls, url: str) -> "Store":
        if url.startswith("sqlite:///"):
            return cls(url[len("sqlite:///"):])
        if url == "sqlite://:memory:":
            return cls(":memory:")
        raise StoreError("only sqlite:/// URLs are supported in this build (PostgreSQL is a later phase)")

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30, isolation_level=None, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        if self.path != ":memory:":
            conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    @contextmanager
    def read(self) -> Iterator[sqlite3.Connection]:
        """Autocommit connection: every SELECT sees the latest committed state (WAL)."""
        if self._memory_conn is not None:
            with self._lock:
                yield self._memory_conn
            return
        yield self._thread_conn()

    @contextmanager
    def write(self) -> Iterator[sqlite3.Connection]:
        """Serialised, transactional write. Rolls back on any exception."""
        with self._lock:
            conn = self._thread_conn()
            try:
                conn.execute("BEGIN IMMEDIATE")
                yield conn
                conn.execute("COMMIT")
            except BaseException:
                conn.execute("ROLLBACK")
                raise

    # ---------- generic helpers ----------

    @staticmethod
    def _page_args(limit: int | None, offset: int | None) -> tuple[int, int]:
        limit = DEFAULT_PAGE_SIZE if limit is None else int(limit)
        offset = 0 if offset is None else int(offset)
        if limit < 1 or limit > MAX_PAGE_SIZE:
            raise StoreError(f"limit must be between 1 and {MAX_PAGE_SIZE}")
        if offset < 0:
            raise StoreError("offset must be >= 0")
        return limit, offset

    def _paged(self, conn: sqlite3.Connection, table: str, where: str, params: list[Any], order: str,
               limit: int | None, offset: int | None, columns: str = "*") -> Page:
        limit, offset = self._page_args(limit, offset)
        total = conn.execute(f"SELECT COUNT(*) FROM {table} {where}", params).fetchone()[0]
        rows = conn.execute(f"SELECT {columns} FROM {table} {where} ORDER BY {order} LIMIT ? OFFSET ?",
                            [*params, limit, offset]).fetchall()
        return Page([_row_to_dict(r) for r in rows], total, limit, offset)

    def audit(self, conn: sqlite3.Connection, at: str, entity: str, entity_id: str, event: str, details: dict[str, Any] | None = None) -> None:
        seq = conn.execute("SELECT COALESCE(MAX(seq), 0) + 1 FROM audit_log").fetchone()[0]
        conn.execute("INSERT INTO audit_log (seq, at, entity, entity_id, event, details_json) VALUES (?, ?, ?, ?, ?, ?)",
                     (seq, at, entity, entity_id, event, json.dumps(details or {}, sort_keys=True)))

    def kv_get(self, key: str) -> str | None:
        with self.read() as conn:
            row = conn.execute("SELECT v FROM kv WHERE k = ?", (key,)).fetchone()
        return None if row is None else row["v"]

    def kv_set(self, key: str, value: str) -> None:
        with self.write() as conn:
            conn.execute("INSERT INTO kv (k, v) VALUES (?, ?) ON CONFLICT (k) DO UPDATE SET v = excluded.v", (key, value))

    # ---------- insights / farmers / calendar ----------

    def upsert_insight(self, conn: sqlite3.Connection, row: dict[str, Any]) -> None:
        cols = ("insight_id", "farmer_id", "created_at", "conversation_language", "resolution_type", "asset_name", "concern",
                "severity", "quality_flag", "schema_valid", "quarantine_reason", "source_file", "line_no", "content_hash",
                "raw_json", "ingested_at", "run_id")
        updates = ", ".join(f"{c} = excluded.{c}" for c in cols if c != "insight_id")
        conn.execute(f"INSERT INTO insights ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)}) "
                     f"ON CONFLICT (insight_id) DO UPDATE SET {updates}", [row.get(c) for c in cols])

    def add_quarantine(self, conn: sqlite3.Connection, row: dict[str, Any]) -> None:
        cols = ("quarantine_id", "source_file", "line_no", "insight_id", "reason", "detail", "raw_text", "ingested_at")
        conn.execute(f"INSERT INTO quarantine ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)}) "
                     "ON CONFLICT (quarantine_id) DO UPDATE SET reason = excluded.reason, detail = excluded.detail, ingested_at = excluded.ingested_at",
                     [row[c] for c in cols])

    def upsert_farmer(self, conn: sqlite3.Connection, row: dict[str, Any]) -> None:
        cols = ("farmer_id", "district", "language", "preferred_channel", "raw_json", "source_file", "line_no")
        updates = ", ".join(f"{c} = excluded.{c}" for c in cols if c != "farmer_id")
        conn.execute(f"INSERT INTO farmers ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)}) "
                     f"ON CONFLICT (farmer_id) DO UPDATE SET {updates}", [row[c] for c in cols])

    def upsert_calendar(self, conn: sqlite3.Connection, row: dict[str, Any]) -> None:
        cols = ("calendar_id", "crop", "growth_stage", "start_date", "end_date", "raw_json", "line_no")
        updates = ", ".join(f"{c} = excluded.{c}" for c in cols if c != "calendar_id")
        conn.execute(f"INSERT INTO crop_calendar ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)}) "
                     f"ON CONFLICT (calendar_id) DO UPDATE SET {updates}", [row[c] for c in cols])

    def record_ingest_run(self, run: dict[str, Any], conn: sqlite3.Connection | None = None) -> None:
        """Insert or update one run. ``seq`` (execution order) and ``recorded_at`` (wall clock) are assigned on
        insert and never changed; simulated ``started_at`` is provenance only. Pass ``conn`` to record inside
        the caller's transaction (the ingestion transaction does this so data and status commit together)."""
        if conn is None:
            with self.write() as c:
                self.record_ingest_run(run, c)
            return
        seq = conn.execute("SELECT COALESCE(MAX(seq), 0) + 1 FROM ingest_runs").fetchone()[0]
        recorded_at = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + f".{int((time.time() % 1) * 1_000_000):06d}Z"
        conn.execute("INSERT INTO ingest_runs (run_id, started_at, finished_at, source_root, status, error, stats_json, seq, recorded_at) "
                     "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
                     "ON CONFLICT (run_id) DO UPDATE SET finished_at = excluded.finished_at, status = excluded.status, error = excluded.error, "
                     "stats_json = excluded.stats_json",
                     (run["run_id"], run["started_at"], run.get("finished_at"), run["source_root"], run.get("status", "running"), run.get("error"),
                      json.dumps(run["stats"], sort_keys=True), seq, recorded_at))

    def latest_ingest_run(self) -> dict[str, Any] | None:
        """The most recently EXECUTED run (by seq), never the one with the latest simulated start time."""
        with self.read() as conn:
            row = conn.execute("SELECT * FROM ingest_runs ORDER BY COALESCE(seq, 0) DESC, recorded_at DESC, run_id DESC LIMIT 1").fetchone()
        if row is None:
            return None
        d = _row_to_dict(row)
        d["stats"] = json.loads(d.pop("stats_json"))
        return d

    def active_ingest_run_id(self) -> str | None:
        """Run id of the dataset currently in use, or None when the latest run is not complete."""
        run = self.latest_ingest_run()
        return run["run_id"] if run is not None and run.get("status") == "complete" else None

    def ingestion_complete(self) -> bool:
        """True only when the most recent ingestion finished successfully."""
        run = self.latest_ingest_run()
        return run is not None and run.get("status") == "complete"

    # ---------- generation claims (M2 / review-2 finding 6) ----------
    #
    # A claim is owned by a fencing TOKEN with a REAL-TIME lease (epoch seconds from time.time()).
    # Simulated season time never touches it. A claim can be taken over only after its lease has
    # expired; the previous owner's token then no longer finalises anything (finish_claim checks it),
    # so a paused worker that wakes up late cannot persist a duplicate survey or hand-off. It may
    # still have performed inference: that cost is unavoidable once a worker outlives its lease
    # (document in README), which is why the lease is long and heartbeat-extendable.

    def claim_generation(self, conn: sqlite3.Connection, insight_id: str, survey_id: str, owner: str, now: str,
                         lease_seconds: int = 300, wall: float | None = None) -> tuple[str, str | None]:
        """Atomically claim the right to generate for one insight.

        Returns (status, token): 'claimed' (proceed with this token), 'busy' (a live lease is held by
        another worker), 'done' (already scheduled), or 'collision' (the survey id belongs to a different
        insight)."""
        wall = time.time() if wall is None else wall
        existing = conn.execute("SELECT insight_id, survey_id, status, token, lease_until FROM generation_claims WHERE insight_id = ? OR survey_id = ?",
                                (insight_id, survey_id)).fetchall()
        for row in existing:
            if row["insight_id"] != insight_id:
                return "collision", None
        mine = next((r for r in existing if r["insight_id"] == insight_id), None)
        token = str(uuid.uuid4())
        if mine is None:
            conn.execute("INSERT INTO generation_claims (insight_id, survey_id, status, owner, token, lease_until, claimed_at, updated_at) "
                         "VALUES (?, ?, 'generating', ?, ?, ?, ?, ?)", (insight_id, survey_id, owner, token, wall + lease_seconds, now, now))
            return "claimed", token
        if mine["status"] == "done":
            return "done", None
        if mine["status"] == "generating" and float(mine["lease_until"]) > wall:
            return "busy", None
        # failed earlier, or the lease has genuinely expired: take over with a fresh token
        cur = conn.execute("UPDATE generation_claims SET status = 'generating', owner = ?, token = ?, lease_until = ?, updated_at = ? "
                           "WHERE insight_id = ? AND (status = 'failed' OR (status = 'generating' AND lease_until <= ?))",
                           (owner, token, wall + lease_seconds, now, insight_id, wall))
        return ("claimed", token) if cur.rowcount == 1 else ("busy", None)

    def heartbeat_claim(self, conn: sqlite3.Connection, insight_id: str, token: str, lease_seconds: int = 300, wall: float | None = None) -> bool:
        """Extend the lease while still owning the claim. False if ownership was lost."""
        wall = time.time() if wall is None else wall
        cur = conn.execute("UPDATE generation_claims SET lease_until = ? WHERE insight_id = ? AND token = ? AND status = 'generating'",
                           (wall + lease_seconds, insight_id, token))
        return cur.rowcount == 1

    def finish_claim(self, conn: sqlite3.Connection, insight_id: str, token: str, status: str, now: str) -> bool:
        """Finalise a claim; only the current owner's token can. False means ownership was lost."""
        cur = conn.execute("UPDATE generation_claims SET status = ?, updated_at = ? WHERE insight_id = ? AND token = ? AND status = 'generating'",
                           (status, now, insight_id, token))
        return cur.rowcount == 1

    def expire_stale_claims(self, wall: float | None = None) -> int:
        """Admin helper: mark claims whose REAL-TIME lease has passed as failed so they can be retried."""
        wall = time.time() if wall is None else wall
        with self.write() as conn:
            cur = conn.execute("UPDATE generation_claims SET status = 'failed' WHERE status = 'generating' AND lease_until <= ?", (wall,))
            return cur.rowcount

    def get_claim(self, insight_id: str) -> dict[str, Any] | None:
        with self.read() as conn:
            row = conn.execute("SELECT * FROM generation_claims WHERE insight_id = ?", (insight_id,)).fetchone()
        return None if row is None else _row_to_dict(row)

    def get_insight(self, insight_id: str) -> dict[str, Any] | None:
        with self.read() as conn:
            row = conn.execute("SELECT * FROM insights WHERE insight_id = ?", (insight_id,)).fetchone()
        return None if row is None else _row_to_dict(row)

    def list_insights(self, *, farmer_id: str | None = None, resolution_type: str | None = None, asset_name: str | None = None,
                      concern: str | None = None, created_from: str | None = None, created_to: str | None = None,
                      schema_valid: bool | None = None, limit: int | None = None, offset: int | None = None) -> Page:
        clauses, params = [], []
        for col, val in (("farmer_id", farmer_id), ("resolution_type", resolution_type), ("asset_name", asset_name), ("concern", concern)):
            if val is not None:
                clauses.append(f"{col} = ?"); params.append(val)
        if created_from:
            clauses.append("created_at >= ?"); params.append(created_from)
        if created_to:
            clauses.append("created_at <= ?"); params.append(created_to)
        if schema_valid is not None:
            clauses.append("schema_valid = ?"); params.append(1 if schema_valid else 0)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        with self.read() as conn:
            return self._paged(conn, "insights", where, params, "created_at, insight_id", limit, offset,
                               columns="insight_id, farmer_id, created_at, conversation_language, resolution_type, asset_name, concern, severity, schema_valid, quarantine_reason, source_file, line_no")

    def iter_insights(self, *, only_valid: bool = True) -> Iterator[dict[str, Any]]:
        with self.read() as conn:
            where = "WHERE schema_valid = 1 AND quarantine_reason IS NULL" if only_valid else ""
            for row in conn.execute(f"SELECT * FROM insights {where} ORDER BY created_at, insight_id"):
                yield _row_to_dict(row)

    def count_insights(self) -> int:
        with self.read() as conn:
            return conn.execute("SELECT COUNT(*) FROM insights").fetchone()[0]

    def list_quarantine(self, limit: int | None = None, offset: int | None = None) -> Page:
        with self.read() as conn:
            return self._paged(conn, "quarantine", "", [], "source_file, line_no", limit, offset,
                               columns="quarantine_id, source_file, line_no, insight_id, reason, detail, ingested_at")

    def get_farmer(self, farmer_id: str) -> dict[str, Any] | None:
        with self.read() as conn:
            row = conn.execute("SELECT * FROM farmers WHERE farmer_id = ?", (farmer_id,)).fetchone()
        return None if row is None else _row_to_dict(row)

    def list_farmers(self, *, district: str | None = None, preferred_channel: str | None = None, limit: int | None = None, offset: int | None = None) -> Page:
        clauses, params = [], []
        if district:
            clauses.append("district = ?"); params.append(district)
        if preferred_channel:
            clauses.append("preferred_channel = ?"); params.append(preferred_channel)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        with self.read() as conn:
            return self._paged(conn, "farmers", where, params, "farmer_id", limit, offset, columns="farmer_id, district, language, preferred_channel")

    def farmer_ids(self) -> set[str]:
        with self.read() as conn:
            return {r[0] for r in conn.execute("SELECT farmer_id FROM farmers")}

    def calendar_rows(self) -> list[dict[str, Any]]:
        with self.read() as conn:
            return [_row_to_dict(r) for r in conn.execute("SELECT * FROM crop_calendar ORDER BY crop, start_date, calendar_id")]

    # ---------- decisions ----------

    def upsert_decision(self, conn: sqlite3.Connection, row: dict[str, Any]) -> None:
        cols = ("insight_id", "farmer_id", "decision", "rule", "internal_reason", "external_reason_code", "reason_text", "details_json", "decided_at", "run_id")
        updates = ", ".join(f"{c} = excluded.{c}" for c in cols if c != "insight_id")
        conn.execute(f"INSERT INTO decisions ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)}) "
                     f"ON CONFLICT (insight_id) DO UPDATE SET {updates}", [row[c] for c in cols])

    def get_decision(self, insight_id: str) -> dict[str, Any] | None:
        with self.read() as conn:
            row = conn.execute("SELECT * FROM decisions WHERE insight_id = ?", (insight_id,)).fetchone()
        return None if row is None else _row_to_dict(row)

    def list_decisions(self, *, decision: str | None = None, rule: str | None = None, farmer_id: str | None = None,
                       limit: int | None = None, offset: int | None = None) -> Page:
        clauses, params = [], []
        for col, val in (("decision", decision), ("rule", rule), ("farmer_id", farmer_id)):
            if val is not None:
                clauses.append(f"{col} = ?"); params.append(val)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        with self.read() as conn:
            return self._paged(conn, "decisions", where, params, "insight_id", limit, offset,
                               columns="insight_id, farmer_id, decision, rule, internal_reason, external_reason_code, reason_text, decided_at")

    def decision_counts(self) -> dict[str, Any]:
        with self.read() as conn:
            by_decision = {r[0]: r[1] for r in conn.execute("SELECT decision, COUNT(*) FROM decisions GROUP BY decision ORDER BY decision")}
            by_rule = {r[0]: r[1] for r in conn.execute("SELECT rule, COUNT(*) FROM decisions GROUP BY rule ORDER BY rule")}
            by_reason = {r[0]: r[1] for r in conn.execute("SELECT internal_reason, COUNT(*) FROM decisions GROUP BY internal_reason ORDER BY internal_reason")}
        return {"by_decision": by_decision, "by_rule": by_rule, "by_internal_reason": by_reason}

    # ---------- surveys / handoffs ----------

    def upsert_survey(self, conn: sqlite3.Connection, row: dict[str, Any]) -> bool:
        """Insert or replace a survey, except that a validated survey (one that may already have a
        hand-off) is never overwritten and never re-assigned to another insight. Returns True if written."""
        cols = ("survey_id", "insight_id", "farmer_id", "language", "status", "generation_source", "attempts", "survey_json",
                "validation_json", "timing_json", "created_at")
        updates = ", ".join(f"{c} = excluded.{c}" for c in cols if c != "survey_id")
        cur = conn.execute(f"INSERT INTO surveys ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)}) "
                           f"ON CONFLICT (survey_id) DO UPDATE SET {updates} "
                           "WHERE surveys.status <> 'validated' AND surveys.insight_id = excluded.insight_id", [row[c] for c in cols])
        return cur.rowcount == 1

    def get_survey(self, survey_id: str) -> dict[str, Any] | None:
        with self.read() as conn:
            row = conn.execute("SELECT * FROM surveys WHERE survey_id = ?", (survey_id,)).fetchone()
        return None if row is None else _row_to_dict(row)

    def get_survey_for_insight(self, insight_id: str) -> dict[str, Any] | None:
        with self.read() as conn:
            row = conn.execute("SELECT * FROM surveys WHERE insight_id = ? ORDER BY survey_id LIMIT 1", (insight_id,)).fetchone()
        return None if row is None else _row_to_dict(row)

    def list_surveys(self, *, farmer_id: str | None = None, status: str | None = None, language: str | None = None,
                     limit: int | None = None, offset: int | None = None) -> Page:
        clauses, params = [], []
        for col, val in (("farmer_id", farmer_id), ("status", status), ("language", language)):
            if val is not None:
                clauses.append(f"{col} = ?"); params.append(val)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        with self.read() as conn:
            return self._paged(conn, "surveys", where, params, "survey_id", limit, offset,
                               columns="survey_id, insight_id, farmer_id, language, status, generation_source, attempts, created_at")

    def survey_counts(self) -> dict[str, int]:
        with self.read() as conn:
            return {r[0]: r[1] for r in conn.execute("SELECT status, COUNT(*) FROM surveys GROUP BY status ORDER BY status")}

    def insert_handoff(self, conn: sqlite3.Connection, row: dict[str, Any]) -> bool:
        """Insert a hand-off once. An existing hand-off (possibly already delivering) is never reset."""
        cols = ("handoff_id", "survey_id", "farmer_id", "priority", "not_before", "not_after", "expires_at", "state", "state_detail",
                "counted_at", "handoff_json", "created_at", "updated_at")
        cur = conn.execute(f"INSERT INTO handoffs ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)}) ON CONFLICT (handoff_id) DO NOTHING",
                           [row[c] for c in cols])
        return cur.rowcount == 1

    def set_handoff_state(self, conn: sqlite3.Connection, handoff_id: str, state: str, at: str, detail: str | None = None,
                          counted_at: str | None = None, keep_counted: bool = True) -> None:
        if counted_at is not None:
            conn.execute("UPDATE handoffs SET state = ?, state_detail = ?, updated_at = ?, counted_at = ? WHERE handoff_id = ?",
                         (state, detail, at, counted_at, handoff_id))
        else:
            conn.execute("UPDATE handoffs SET state = ?, state_detail = ?, updated_at = ? WHERE handoff_id = ?", (state, detail, at, handoff_id))
        self.audit(conn, at, "handoff", handoff_id, f"state:{state}", {"detail": detail})

    def get_handoff(self, handoff_id: str) -> dict[str, Any] | None:
        with self.read() as conn:
            row = conn.execute("SELECT * FROM handoffs WHERE handoff_id = ?", (handoff_id,)).fetchone()
        return None if row is None else _row_to_dict(row)

    def get_handoff_for_survey(self, survey_id: str) -> dict[str, Any] | None:
        with self.read() as conn:
            row = conn.execute("SELECT * FROM handoffs WHERE survey_id = ? ORDER BY handoff_id LIMIT 1", (survey_id,)).fetchone()
        return None if row is None else _row_to_dict(row)

    def list_handoffs(self, *, state: str | None = None, farmer_id: str | None = None, priority: str | None = None,
                      limit: int | None = None, offset: int | None = None) -> Page:
        clauses, params = [], []
        for col, val in (("state", state), ("farmer_id", farmer_id), ("priority", priority)):
            if val is not None:
                clauses.append(f"{col} = ?"); params.append(val)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        with self.read() as conn:
            return self._paged(conn, "handoffs", where, params, "not_before, handoff_id", limit, offset,
                               columns="handoff_id, survey_id, farmer_id, priority, not_before, not_after, expires_at, state, state_detail, counted_at, updated_at")

    def handoff_counts(self) -> dict[str, int]:
        with self.read() as conn:
            return {r[0]: r[1] for r in conn.execute("SELECT state, COUNT(*) FROM handoffs GROUP BY state ORDER BY state")}

    def iter_handoffs(self, states: tuple[str, ...], due_by: str | None = None) -> list[dict[str, Any]]:
        """Active hand-offs. With ``due_by``, hand-offs whose window has not opened yet are skipped
        unless they are already in progress (so a tick does not scan the whole future)."""
        marks = ", ".join("?" for _ in states)
        params: list[Any] = list(states)
        where = f"state IN ({marks})"
        if due_by is not None:
            where += " AND (state = 'in_progress' OR not_before <= ?)"
            params.append(due_by)
        with self.read() as conn:
            return [_row_to_dict(r) for r in conn.execute(f"SELECT * FROM handoffs WHERE {where} ORDER BY not_before, handoff_id", params)]

    def claim_attempt(self, conn: sqlite3.Connection, row: dict[str, Any]) -> bool:
        """Insert a delivery attempt once (the attempt key is the claim). False if it already exists."""
        cols = ("attempt_key", "handoff_id", "survey_id", "channel", "channel_index", "delivery_attempt", "state", "scheduled_for",
                "sent_at", "outcome_status", "failure_code", "response_key", "created_at", "updated_at")
        cur = conn.execute(f"INSERT INTO delivery_attempts ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)}) ON CONFLICT (attempt_key) DO NOTHING",
                           [row[c] for c in cols])
        return cur.rowcount == 1

    def handoff_state(self, conn: sqlite3.Connection, handoff_id: str) -> str | None:
        row = conn.execute("SELECT state FROM handoffs WHERE handoff_id = ?", (handoff_id,)).fetchone()
        return None if row is None else row["state"]

    def farmer_counted_between(self, conn: sqlite3.Connection, farmer_id: str, start: str, end: str, exclude_handoff: str) -> int:
        """Surveys occupying the farmer's cap window: counted ones, plus in-flight sends not yet resolved.

        An in-flight survey holds a slot until its outcome is known; if it turns out not to count
        (e.g. delivery failed) the slot is released when the hand-off leaves in_progress."""
        return conn.execute(
            "SELECT COUNT(*) FROM handoffs h WHERE h.farmer_id = ? AND h.handoff_id <> ? AND ("
            "  (h.counted_at IS NOT NULL AND h.counted_at >= ? AND h.counted_at < ?) OR"
            "  (h.counted_at IS NULL AND h.state = 'in_progress' AND EXISTS ("
            "     SELECT 1 FROM delivery_attempts a WHERE a.handoff_id = h.handoff_id AND a.sent_at IS NOT NULL AND a.sent_at >= ? AND a.sent_at < ?)))",
            (farmer_id, exclude_handoff, start, end, start, end)).fetchone()[0]

    # ---------- delivery attempts / responses ----------

    def upsert_attempt(self, conn: sqlite3.Connection, row: dict[str, Any]) -> None:
        cols = ("attempt_key", "handoff_id", "survey_id", "channel", "channel_index", "delivery_attempt", "state", "scheduled_for",
                "sent_at", "outcome_status", "failure_code", "response_key", "created_at", "updated_at")
        updates = ", ".join(f"{c} = excluded.{c}" for c in cols if c not in ("attempt_key", "created_at"))
        conn.execute(f"INSERT INTO delivery_attempts ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)}) "
                     f"ON CONFLICT (attempt_key) DO UPDATE SET {updates}", [row[c] for c in cols])

    def attempts_for_handoff(self, handoff_id: str) -> list[dict[str, Any]]:
        with self.read() as conn:
            return [_row_to_dict(r) for r in conn.execute(
                "SELECT * FROM delivery_attempts WHERE handoff_id = ? ORDER BY channel_index, delivery_attempt", (handoff_id,))]

    def list_attempts(self, *, state: str | None = None, channel: str | None = None, limit: int | None = None, offset: int | None = None) -> Page:
        clauses, params = [], []
        for col, val in (("state", state), ("channel", channel)):
            if val is not None:
                clauses.append(f"{col} = ?"); params.append(val)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        with self.read() as conn:
            return self._paged(conn, "delivery_attempts", where, params, "scheduled_for, attempt_key", limit, offset)

    def attempt_counts(self) -> dict[str, int]:
        with self.read() as conn:
            return {r[0]: r[1] for r in conn.execute("SELECT state, COUNT(*) FROM delivery_attempts GROUP BY state ORDER BY state")}

    def insert_response(self, conn: sqlite3.Connection, row: dict[str, Any]) -> bool:
        """Insert once per response_key. Returns False if the key already existed (duplicate)."""
        cols = ("response_key", "survey_id", "farmer_id", "channel", "status", "failure_code", "needs_follow_up", "counts_toward_cap", "recorded_at", "record_json")
        cur = conn.execute(f"INSERT INTO responses ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)}) ON CONFLICT (response_key) DO NOTHING",
                           [row[c] for c in cols])
        return cur.rowcount == 1

    def get_response(self, response_key: str) -> dict[str, Any] | None:
        with self.read() as conn:
            row = conn.execute("SELECT * FROM responses WHERE response_key = ?", (response_key,)).fetchone()
        return None if row is None else _row_to_dict(row)

    def list_responses(self, *, survey_id: str | None = None, status: str | None = None, needs_follow_up: bool | None = None,
                       limit: int | None = None, offset: int | None = None) -> Page:
        clauses, params = [], []
        for col, val in (("survey_id", survey_id), ("status", status)):
            if val is not None:
                clauses.append(f"{col} = ?"); params.append(val)
        if needs_follow_up is not None:
            clauses.append("needs_follow_up = ?"); params.append(1 if needs_follow_up else 0)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        with self.read() as conn:
            return self._paged(conn, "responses", where, params, "recorded_at, response_key", limit, offset,
                               columns="response_key, survey_id, farmer_id, channel, status, failure_code, needs_follow_up, counts_toward_cap, recorded_at")

    def response_counts(self) -> dict[str, Any]:
        with self.read() as conn:
            by_status = {r[0]: r[1] for r in conn.execute("SELECT status, COUNT(*) FROM responses GROUP BY status ORDER BY status")}
            follow = conn.execute("SELECT COUNT(*) FROM responses WHERE needs_follow_up = 1").fetchone()[0]
        return {"by_status": by_status, "needs_follow_up": follow}

    def survey_has_accepted_answer(self, conn: sqlite3.Connection, survey_id: str) -> bool:
        row = conn.execute("SELECT 1 FROM responses WHERE survey_id = ? AND status IN ('completed', 'partial', 'negative_outcome') LIMIT 1", (survey_id,)).fetchone()
        return row is not None

    # ---------- audit ----------

    def list_audit(self, *, entity: str | None = None, entity_id: str | None = None, limit: int | None = None, offset: int | None = None) -> Page:
        clauses, params = [], []
        for col, val in (("entity", entity), ("entity_id", entity_id)):
            if val is not None:
                clauses.append(f"{col} = ?"); params.append(val)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        with self.read() as conn:
            return self._paged(conn, "audit_log", where, params, "seq", limit, offset)
