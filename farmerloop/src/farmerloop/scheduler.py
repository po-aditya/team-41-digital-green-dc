"""Durable, offline scheduling guards. No transport or AWS calls.

A claim reserves ONE attempt; it is not proof of delivery. An unresolved claim
is never automatically resent after a restart. A trusted local adapter supplies
observations/verified identity; this module is not a network authentication API.
"""

from contextlib import contextmanager
from datetime import datetime, time, timedelta, timezone
from hashlib import sha256
import json
import sqlite3
from uuid import uuid4

from . import config
from .respond import build_response
from .schedule import build_handoff
from .simulate import simulate
from .validate import validate

IST = timezone(timedelta(hours=5, minutes=30))
EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
MICROSECOND = timedelta(microseconds=1)


def _dt(value):
    value = datetime.fromisoformat(value) if isinstance(value, str) else value
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Scheduler timestamps must be timezone-aware")
    return value.astimezone(IST)


def _us(value):
    return (_dt(value) - EPOCH) // MICROSECOND


def _iso(value):
    return (EPOCH + value * MICROSECOND).astimezone(IST).isoformat()


def _json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


class Scheduler:
    """SQLite state isolated by run_id; one connection per worker/thread.

    Cap interval: (now - 7 days, now], distinct surveys across all channels.
    First observed display counts immediately. Otherwise the response's official
    counts_toward_cap flag controls counting, using opened/answered time or the
    recorded time as a conservative fallback. Retries never refresh that date.
    """

    def __init__(self, path, *, run_id="default", max_channel_attempts=3):
        if not isinstance(run_id, str) or not run_id.strip():
            raise ValueError("A nonempty run_id is required")
        response_schema = json.loads((config.SCHEMA_DIR / "response.schema.json").read_text())
        max_attempts = response_schema["properties"]["delivery_attempt"]["maximum"]
        if type(max_channel_attempts) is not int or not 1 <= max_channel_attempts <= max_attempts:
            raise ValueError(f"max_channel_attempts must be an integer from 1 to {max_attempts}")
        self.run_id = run_id
        self.max_channel_attempts = max_channel_attempts
        self.rules = json.loads(config.RULES_JSON.read_text())
        self.cap = self.rules["frequency_cap"]
        policy = _json({"rules": self.rules,
                        "outcomes": json.loads(config.OUTCOME_CODES_JSON.read_text()),
                        "response_schema": response_schema,
                        "max_channel_attempts": max_channel_attempts})
        self.policy_hash = sha256(policy.encode()).hexdigest()
        self.db = sqlite3.connect(str(path), timeout=10, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        try:
            with self._transaction() as db:
                version = db.execute("PRAGMA user_version").fetchone()[0]
                if version not in (0, 1):
                    raise ValueError(f"Unsupported scheduler database version: {version}")
                # Each DDL statement stays in this transaction (no executescript).
                statements = (
                    "CREATE TABLE IF NOT EXISTS runs (run_id TEXT PRIMARY KEY, clock_us INTEGER, policy_hash TEXT NOT NULL)",
                    "CREATE TABLE IF NOT EXISTS jobs (run_id TEXT, survey_id TEXT, farmer_id TEXT NOT NULL, insight TEXT NOT NULL, handoff TEXT NOT NULL, state TEXT NOT NULL, channel_index INTEGER NOT NULL, ready_us INTEGER NOT NULL, reason TEXT NOT NULL, PRIMARY KEY(run_id,survey_id), FOREIGN KEY(run_id) REFERENCES runs(run_id))",
                    "CREATE TABLE IF NOT EXISTS attempts (run_id TEXT, attempt_id TEXT, survey_id TEXT NOT NULL, channel_index INTEGER NOT NULL, channel TEXT NOT NULL, number INTEGER NOT NULL, claimed_us INTEGER NOT NULL, shown_us INTEGER, response TEXT, PRIMARY KEY(run_id,attempt_id), UNIQUE(run_id,survey_id,channel_index,number), FOREIGN KEY(run_id,survey_id) REFERENCES jobs(run_id,survey_id))",
                    "CREATE TABLE IF NOT EXISTS cap_events (run_id TEXT, survey_id TEXT, farmer_id TEXT NOT NULL, asked_us INTEGER NOT NULL, PRIMARY KEY(run_id,survey_id), FOREIGN KEY(run_id,survey_id) REFERENCES jobs(run_id,survey_id))",
                    "CREATE TABLE IF NOT EXISTS optouts (run_id TEXT, farmer_id TEXT, at_us INTEGER NOT NULL, source TEXT NOT NULL, PRIMARY KEY(run_id,farmer_id), FOREIGN KEY(run_id) REFERENCES runs(run_id))",
                    "CREATE TABLE IF NOT EXISTS decisions (seq INTEGER PRIMARY KEY, run_id TEXT NOT NULL, at_us INTEGER NOT NULL, survey_id TEXT, action TEXT NOT NULL, reason TEXT NOT NULL, FOREIGN KEY(run_id) REFERENCES runs(run_id))",
                    "CREATE INDEX IF NOT EXISTS cap_farmer ON cap_events(run_id,farmer_id,asked_us)",
                )
                for statement in statements:
                    db.execute(statement)
                db.execute("PRAGMA user_version=1")
                db.execute("INSERT OR IGNORE INTO runs VALUES (?,NULL,?)", (run_id, self.policy_hash))
                if db.execute("SELECT policy_hash FROM runs WHERE run_id=?", (run_id,)).fetchone()[0] != self.policy_hash:
                    raise ValueError("Scheduler policy changed; use a new run or an explicit migration")
        except Exception:
            self.close()
            raise

    def close(self):
        self.db.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    @contextmanager
    def _transaction(self):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield self.db
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise

    def _clock(self, db, now):
        tick = _us(now)
        previous = db.execute("SELECT clock_us FROM runs WHERE run_id=?", (self.run_id,)).fetchone()[0]
        if previous is not None and tick < previous:
            raise ValueError("Simulated clock cannot move backwards; use a separate run")
        db.execute("UPDATE runs SET clock_us=? WHERE run_id=?", (tick, self.run_id))
        return tick

    def _job(self, db, sid):
        row = db.execute("SELECT * FROM jobs WHERE run_id=? AND survey_id=?", (self.run_id, sid)).fetchone()
        if row is None:
            raise ValueError("Unknown survey in this scheduler run")
        return row

    def _attempt(self, db, attempt_id):
        row = db.execute("SELECT * FROM attempts WHERE run_id=? AND attempt_id=?", (self.run_id, attempt_id)).fetchone()
        if row is None:
            raise ValueError("Unknown attempt in this scheduler run")
        return row

    def _log(self, db, tick, sid, action, reason):
        db.execute("INSERT INTO decisions(run_id,at_us,survey_id,action,reason) VALUES (?,?,?,?,?)",
                   (self.run_id, tick, sid, action, reason))

    def enqueue(self, insight, survey, window, *, now):
        """Fresh boundary validation; duplicate immutable submissions create no jobs."""
        handoff = build_handoff(insight, survey, window, created_at=_dt(now))
        raw = insight.model_dump(mode="json", exclude_unset=True)
        sid = survey.survey_id
        with self._transaction() as db:
            tick = self._clock(db, now)
            existing = db.execute("SELECT * FROM jobs WHERE run_id=? AND survey_id=?", (self.run_id, sid)).fetchone()
            if existing:
                previous = json.loads(existing["handoff"])
                # A retry may have a later submission time, but not changed content.
                previous.pop("created_at")
                comparison = dict(handoff)
                comparison.pop("created_at")
                if previous != comparison or json.loads(existing["insight"]) != raw:
                    raise ValueError("Conflicting survey ID: existing immutable job differs")
                return {"survey_id": sid, "status": "duplicate"}
            db.execute("INSERT INTO jobs VALUES (?,?,?,?,?,'queued',0,?,'enqueued')",
                       (self.run_id, sid, survey.farmer_id, _json(raw), _json(handoff),
                        _us(handoff["send_window"]["not_before"])))
            self._log(db, tick, sid, "enqueued", "validated_handoff")
        return {"survey_id": sid, "status": "enqueued"}

    def claim(self, survey_id, *, now):
        """Atomically reserve an attempt or return an explicit defer/drop reason.

        No I/O is sent. A caller must not treat a repeated in_flight result as
        authorization to send again. Unknown delivery never expires into retry.
        """
        with self._transaction() as db:
            tick = self._clock(db, now)
            job = self._job(db, survey_id)
            h = json.loads(job["handoff"])
            def outcome(action, reason, *, terminal=False):
                db.execute("UPDATE jobs SET reason=?,state=? WHERE run_id=? AND survey_id=?",
                           (reason, "dropped" if terminal else job["state"], self.run_id, survey_id))
                self._log(db, tick, survey_id, action, reason)
                return {"decision": action, "reason": reason, "survey_id": survey_id}
            if job["state"] in ("finished", "dropped"):
                return outcome("done", job["reason"])
            opted_out = db.execute("SELECT 1 FROM optouts WHERE run_id=? AND farmer_id=?",
                                  (self.run_id, job["farmer_id"])).fetchone()
            if opted_out:
                return outcome("blocked", "farmer_opted_out", terminal=True)
            if job["state"] == "in_flight":
                return outcome("in_flight", "awaiting_attempt_outcome")
            if tick >= _us(h["expires_at"]):
                return outcome("blocked", "expired", terminal=True)
            if tick > _us(h["send_window"]["not_after"]):
                return outcome("blocked", "send_window_closed", terminal=True)
            if tick < job["ready_us"]:
                return outcome("deferred", "not_due")
            clock = _dt(now).time()
            if not time.fromisoformat(h["send_hours"]["from"]) <= clock <= time.fromisoformat(h["send_hours"]["to"]):
                return outcome("deferred", "outside_send_hours")
            if not h["frequency_cap"]["exempt"]:
                since = tick - self.cap["window_days"] * 86400 * 1_000_000
                count = db.execute("SELECT count(*) FROM cap_events WHERE run_id=? AND farmer_id=? AND survey_id<>? AND asked_us>? AND asked_us<=?",
                                   (self.run_id, job["farmer_id"], survey_id, since, tick)).fetchone()[0]
                if count >= self.cap["max_surveys"]:
                    return outcome("deferred", "weekly_cap")
                unresolved = db.execute("""SELECT 1 FROM attempts a JOIN jobs j
                    ON j.run_id=a.run_id AND j.survey_id=a.survey_id
                    WHERE a.run_id=? AND j.farmer_id=? AND a.survey_id<>? AND a.response IS NULL
                    AND NOT EXISTS(SELECT 1 FROM cap_events c WHERE c.run_id=a.run_id AND c.survey_id=a.survey_id)
                    LIMIT 1""", (self.run_id, job["farmer_id"], survey_id)).fetchone()
                if unresolved:
                    return outcome("deferred", "unresolved_attempt_reservation")
            index = job["channel_index"]
            channel = h["channel_order"][index]["channel"]
            number = db.execute("SELECT count(*)+1 FROM attempts WHERE run_id=? AND survey_id=? AND channel_index=?",
                                (self.run_id, survey_id, index)).fetchone()[0]
            identity = "sim-attempt-" + uuid4().hex
            # Response.schema.json permits whole seconds only. All permission
            # checks above use full precision; project only the dispatched
            # record's timestamp to the contract's precision, never the checks.
            sent_tick = tick // 1_000_000 * 1_000_000
            db.execute("INSERT INTO attempts VALUES (?,?,?,?,?,?,?,NULL,NULL)",
                       (self.run_id, identity, survey_id, index, channel, number, sent_tick))
            db.execute("UPDATE jobs SET state='in_flight',reason='attempt_reserved' WHERE run_id=? AND survey_id=?", (self.run_id, survey_id))
            self._log(db, tick, survey_id, "claimed", identity)
            return {"decision": "claimed", "reason": "attempt_reserved", "survey_id": survey_id,
                    "attempt_id": identity, "channel": channel, "delivery_attempt": number,
                    "sent_at": _iso(sent_tick), "survey": h["survey"]}

    def _count(self, db, job, asked):
        db.execute("""INSERT INTO cap_events VALUES (?,?,?,?)
            ON CONFLICT(run_id,survey_id) DO UPDATE SET asked_us=MIN(cap_events.asked_us,excluded.asked_us)""",
                   (self.run_id, job["survey_id"], job["farmer_id"], asked))

    def acknowledge_shown(self, attempt_id, *, shown_at, verified_farmer_id, now):
        """Trusted adapter reports the actual display; delivery receipt alone is not display."""
        with self._transaction() as db:
            tick = self._clock(db, now)
            attempt = self._attempt(db, attempt_id)
            job = self._job(db, attempt["survey_id"])
            if verified_farmer_id != job["farmer_id"]:
                raise ValueError("Display identity does not match the survey farmer")
            shown = _us(shown_at)
            if not attempt["claimed_us"] <= shown <= tick:
                raise ValueError("Display timestamp is before dispatch or in the future")
            if attempt["response"] is not None:
                if attempt["shown_us"] == shown:
                    return
                raise ValueError("Attempt already finalized; display correction requires reconciliation")
            if attempt["shown_us"] is not None and attempt["shown_us"] != shown:
                raise ValueError("Conflicting display timestamp")
            db.execute("UPDATE attempts SET shown_us=? WHERE run_id=? AND attempt_id=?", (shown, self.run_id, attempt_id))
            self._count(db, job, shown)
            self._log(db, tick, job["survey_id"], "shown", attempt_id)

    def _opt_out(self, db, farmer, tick, source):
        db.execute("INSERT OR IGNORE INTO optouts VALUES (?,?,?,?)", (self.run_id, farmer, tick, source))
        db.execute("UPDATE jobs SET state='dropped',reason='farmer_opted_out' WHERE run_id=? AND farmer_id=? AND state='queued'",
                   (self.run_id, farmer))

    def opt_out(self, farmer_id, *, verified_farmer_id, now):
        """Preference event from a trusted adapter; decline is not this operation."""
        if not farmer_id or farmer_id != verified_farmer_id:
            raise ValueError("Opt-out identity does not match the farmer")
        with self._transaction() as db:
            tick = self._clock(db, now)
            self._opt_out(db, farmer_id, tick, "verified_preference")
            self._log(db, tick, None, "opted_out", farmer_id)

    def complete(self, attempt_id, *, items, timestamps, recorded_at, answered_by,
                 now, event=None, raw_event=None):
        """Accept observations, deriving cap/retry fields with the existing builder.

        The caller cannot supply status, cap flags, farmer_id or retry decisions.
        Exact replay is idempotent; a conflicting final snapshot is rejected.
        """
        return self._complete(attempt_id, now, lambda survey, attempt, handoff: build_response(
            survey, channel=attempt["channel"], items=items, timestamps=timestamps,
            recorded_at=recorded_at, response_key=attempt_id, answered_by=answered_by,
            event=event, delivery_attempt=attempt["number"], raw_event=raw_event))

    def complete_simulated(self, attempt_id, case, *, now):
        """Script one offline outcome through the existing simulator and response builder."""
        def factory(survey, attempt, handoff):
            record = simulate(survey, attempt["channel"], case,
                              sent_at=_dt(_iso(attempt["claimed_us"])).replace(tzinfo=None),
                              expires_at=_dt(handoff["expires_at"]).replace(tzinfo=None),
                              delivery_attempt=attempt["number"])
            record["response_key"] = attempt_id
            return record
        return self._complete(attempt_id, now, factory)

    def _complete(self, attempt_id, now, factory):
        with self._transaction() as db:
            tick = self._clock(db, now)
            attempt = self._attempt(db, attempt_id)
            job = self._job(db, attempt["survey_id"])
            h = json.loads(job["handoff"])
            record = factory(h["survey"], attempt, h)
            errors = validate("response", record)
            if errors:
                raise ValueError("Invalid response: " + "; ".join(errors[:3]))
            encoded = _json(record)
            if attempt["response"] is not None:
                if attempt["response"] != encoded:
                    raise ValueError("Conflicting final attempt record")
                return {"status": "duplicate", "response": record}
            stamps = record["timestamps"]
            recorded = _us(record["recorded_at"])
            values = [_us(stamps[k]) for k in ("sent", "delivered", "opened", "answered") if stamps[k] is not None]
            if stamps["sent"] is None or _us(stamps["sent"]) != attempt["claimed_us"]:
                raise ValueError("Response sent timestamp does not match its reserved attempt")
            if not values or values != sorted(values) or values[0] < attempt["claimed_us"] or values[-1] > recorded or recorded > tick:
                raise ValueError("Response chronology is invalid or in the future")
            answer_time = stamps["answered"] or record["recorded_at"]
            if record["answers"] and _us(answer_time) >= _us(h["expires_at"]):
                raise ValueError("Late answers require a stale outcome, not accepted answers")
            if record["failure_code"] == "farmer_opted_out" and record["answered_by"] != job["farmer_id"]:
                raise ValueError("Opt-out requires the verified survey farmer identity")
            if record["answers"] and record["answered_by"] != job["farmer_id"]:
                raise ValueError("Accepted answers require the verified survey farmer identity")
            if attempt["shown_us"] is not None and attempt["shown_us"] > recorded:
                raise ValueError("Final record predates the recorded display")
            if attempt["shown_us"] is not None and record["failure_code"] in {
                "push_token_invalid", "client_cannot_render", "wa_session_window_closed",
                "wa_undelivered", "tg_bot_blocked", "voice_no_answer", "voice_busy"}:
                raise ValueError("Confirmed display contradicts a never-delivered outcome")
            if record["counts_toward_cap"]:
                # Prefer actual display; otherwise an answer proves the survey
                # was seen. With neither, use recording time conservatively.
                observed = stamps["opened"] or stamps["answered"] or record["recorded_at"]
                self._count(db, job, min(_us(observed), attempt["shown_us"] or _us(observed)))
            db.execute("UPDATE attempts SET response=? WHERE run_id=? AND attempt_id=?", (encoded, self.run_id, attempt_id))
            state, reason, index = "finished", record["status"], job["channel_index"]
            retry = record["retry_decision"]
            if retry == "fall_back_to_next_channel" and index + 1 < len(h["channel_order"]):
                state, reason, index = "queued", "channel_fallback", index + 1
            elif retry == "retry_same_channel" and attempt["number"] < self.max_channel_attempts:
                state, reason = "queued", "retry_same_channel"
            elif retry in ("retry_same_channel", "fall_back_to_next_channel"):
                reason = "retry_exhausted"
            if record["failure_code"] == "farmer_opted_out":
                self._opt_out(db, job["farmer_id"], recorded, attempt_id)
            if db.execute("SELECT 1 FROM optouts WHERE run_id=? AND farmer_id=?", (self.run_id, job["farmer_id"])).fetchone():
                state, reason = "dropped", "farmer_opted_out"
            delay = (record["retry_after_minutes"] or 0) * 60 * 1_000_000
            db.execute("UPDATE jobs SET state=?,reason=?,channel_index=?,ready_us=? WHERE run_id=? AND survey_id=?",
                       (state, reason, index, tick + delay, self.run_id, job["survey_id"]))
            self._log(db, tick, job["survey_id"], "recorded", reason)
            return {"status": "accepted", "response": record}

    def snapshot(self):
        """Consistent read-only state for a demo or diagnostics; no dispatch side effects."""
        with self._transaction() as db:
            result = {"run_id": self.run_id, "schema_version": 1, "policy_hash": self.policy_hash}
            result["clock"] = db.execute("SELECT clock_us FROM runs WHERE run_id=?", (self.run_id,)).fetchone()[0]
            for table in ("jobs", "attempts", "cap_events", "optouts", "decisions"):
                rows = [dict(r) for r in db.execute(f"SELECT * FROM {table} WHERE run_id=? ORDER BY rowid", (self.run_id,))]
                for row in rows:
                    for key in ("insight", "handoff", "response"):
                        if row.get(key) is not None:
                            row[key] = json.loads(row[key])
                result[table] = rows
            return result

    def reset_demo(self, *, confirm_run_id):
        """Explicit reset of one named demo run; never reset a production/default run."""
        if not self.run_id.startswith("demo-") or confirm_run_id != self.run_id:
            raise ValueError("Reset requires the exact current demo- run ID")
        with self._transaction() as db:
            for table in ("decisions", "attempts", "cap_events", "optouts", "jobs"):
                db.execute(f"DELETE FROM {table} WHERE run_id=?", (self.run_id,))
            db.execute("UPDATE runs SET clock_us=NULL WHERE run_id=?", (self.run_id,))
