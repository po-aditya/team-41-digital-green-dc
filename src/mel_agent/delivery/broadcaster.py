"""Scheduler + broadcaster stub over the simulated clock.

State machine per hand-off (table ``handoffs.state``):

  scheduled ──(window open, in send hours, cap ok)──▶ in_progress ──▶ answered | declined | expired | undeliverable
      │                                                   ▲
      ├──(cap full)──▶ waiting_cap ───────────────────────┘ (retried every tick; cap_suppressed at window end)
      ├──(farmer opted out earlier)──▶ suppressed_opt_out
      ├──(survey text fails the content policy)──▶ blocked_unsafe
      └──(expires_at passed before any send)──▶ expired_unsent

Per channel attempt (table ``delivery_attempts``): awaiting (sent, farmer has not
reacted yet) → answered | failed | moved_on | expired. A finished attempt leaves a
successor marker row (``retry_scheduled`` / ``fallback_scheduled``) in the SAME
transaction, so a crash between "this attempt is over" and "the next one was sent"
is recovered on the next tick by whichever process runs it.

Concurrency: the decision to send is a single ``BEGIN IMMEDIATE`` transaction that
re-reads the hand-off state, counts the farmer's cap (including in-flight sends)
and inserts the attempt row (its primary key is the claim). Two workers, threads or
processes, cannot both claim the same attempt or both pass the cap for one farmer.

Nothing here contacts a real channel; exactly-once delivery to a real provider
would need the provider's own idempotency key and is not claimed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from mel_agent.config import Settings
from mel_agent.contracts import SchemaName, SchemaRegistry
from mel_agent.data.pack import OutcomeCodes, Rules
from mel_agent.delivery.clock import SimulatedClock
from mel_agent.delivery.simulator import SUCCESS_STATUSES, Simulator
from mel_agent.generation.safety import validate_survey_text
from mel_agent.store import Store
from mel_agent.time_utils import format_ist, parse_hhmm, parse_ist

TERMINAL_STATES = ("answered", "declined", "expired", "expired_unsent", "undeliverable", "cap_suppressed", "suppressed_opt_out", "blocked_unsafe")
ACTIVE_STATES = ("scheduled", "waiting_cap", "in_progress")
MAX_TICKS = 20_000
MIN_STEP_MINUTES, MAX_STEP_MINUTES = 1, 1440


@dataclass
class TickReport:
    at: str
    sent: int = 0
    answered: int = 0
    failed: int = 0
    moved_on: int = 0
    expired: int = 0
    cap_deferred_ticks: int = 0  # counted per tick, not per hand-off
    cap_suppressed: int = 0
    opt_out_suppressed: int = 0
    blocked_unsafe: int = 0
    claims_lost: int = 0  # another worker claimed the same attempt first
    duplicates_ignored: int = 0
    schema_invalid_records: int = 0
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


class Broadcaster:
    def __init__(self, store: Store, rules: Rules, outcome_codes: OutcomeCodes, registry: SchemaRegistry, settings: Settings,
                 clock: SimulatedClock, simulator: Simulator) -> None:
        self.store = store
        self.rules = rules
        self.codes = outcome_codes
        self.registry = registry
        self.settings = settings
        self.clock = clock
        self.simulator = simulator

    # ---------- helpers ----------

    def _in_send_hours(self, now: datetime, handoff: dict[str, Any]) -> bool:
        hours = handoff["send_hours"]
        return parse_hhmm(hours["from"]) <= now.time() <= parse_hhmm(hours["to"])

    def _opted_out(self, farmer_id: str) -> bool:
        return self.store.kv_get(f"optout:{farmer_id}") == "1"

    def _cap_full(self, conn, handoff: dict[str, Any], now: datetime) -> bool:
        cap = handoff["frequency_cap"]
        if cap["exempt"]:
            return False
        start = format_ist(now - timedelta(days=int(cap["window_days"])))
        count = self.store.farmer_counted_between(conn, handoff["survey"]["farmer_id"], start, format_ist(now + timedelta(seconds=1)), handoff["handoff_id"])
        return count >= int(cap["max_surveys"])

    def _attempt_key(self, handoff_id: str, channel: str, attempt: int) -> str:
        return f"{handoff_id}:{channel}:{attempt}"

    def _store_response(self, conn, record: dict[str, Any], report: TickReport) -> bool:
        errors = self.registry.errors(SchemaName.RESPONSE, record)
        if errors:
            report.schema_invalid_records += 1
            report.notes.append(f"response {record.get('response_key')} failed schema: {errors[0].path} {errors[0].validator}")
            return False
        inserted = self.store.insert_response(conn, {
            "response_key": record["response_key"], "survey_id": record["survey_id"], "farmer_id": record["farmer_id"],
            "channel": record["channel"], "status": record["status"], "failure_code": record["failure_code"],
            "needs_follow_up": 1 if record["needs_follow_up"] else 0, "counts_toward_cap": 1 if record["counts_toward_cap"] else 0,
            "recorded_at": record["recorded_at"], "record_json": json.dumps(record, ensure_ascii=False, sort_keys=True),
        })
        if not inserted:
            report.duplicates_ignored += 1
        return inserted

    # ---------- main loop ----------

    def tick(self) -> TickReport:
        now = self.clock.now
        report = TickReport(at=format_ist(now))
        for row in self.store.iter_handoffs(ACTIVE_STATES, due_by=format_ist(now)):
            handoff = json.loads(row["handoff_json"])
            try:
                self._process(row, handoff, now, report)
            except Exception as exc:  # one broken hand-off must not stop the batch
                report.notes.append(f"{row['handoff_id']}: {type(exc).__name__}")
                with self.store.write() as conn:
                    self.store.audit(conn, format_ist(now), "handoff", row["handoff_id"], "error", {"type": type(exc).__name__})
        return report

    def run_until(self, until: datetime | str, step_minutes: int = 60) -> list[TickReport]:
        end = parse_ist(until) if isinstance(until, str) else until
        if not isinstance(step_minutes, int) or isinstance(step_minutes, bool) or not (MIN_STEP_MINUTES <= step_minutes <= MAX_STEP_MINUTES):
            raise ValueError(f"step_minutes must be an integer between {MIN_STEP_MINUTES} and {MAX_STEP_MINUTES}")
        if end < self.clock.now:
            raise ValueError("the simulated clock only moves forward")
        ticks = int((end - self.clock.now).total_seconds() // (step_minutes * 60)) + 1
        if ticks > MAX_TICKS:
            raise ValueError(f"run would take {ticks} ticks; the limit is {MAX_TICKS}. Use a larger step or a nearer 'until'")
        reports = []
        while self.clock.now <= end:
            reports.append(self.tick())
            self.clock.advance(minutes=step_minutes)
        return reports

    def _process(self, row: dict[str, Any], handoff: dict[str, Any], now: datetime, report: TickReport) -> None:
        hid = row["handoff_id"]
        survey = handoff["survey"]
        farmer_id = survey["farmer_id"]
        not_before, not_after, expires = parse_ist(handoff["send_window"]["not_before"]), parse_ist(handoff["send_window"]["not_after"]), parse_ist(handoff["expires_at"])
        now_s = format_ist(now)

        if row["state"] == "scheduled" and self._opted_out(farmer_id):
            with self.store.write() as conn:
                if self.store.handoff_state(conn, hid) == "scheduled":
                    self.store.set_handoff_state(conn, hid, "suppressed_opt_out", now_s, "farmer asked for no more surveys")
                    report.opt_out_suppressed += 1
            return
        if now < not_before and row["state"] in ("scheduled", "waiting_cap"):
            return  # nothing can have been sent yet; cheap exit

        attempts = self.store.attempts_for_handoff(hid)
        # Pending farmer reactions become visible when the clock passes their time.
        self._materialise_reactions(hid, survey, attempts, now, report)
        attempts = self.store.attempts_for_handoff(hid)

        if now > expires:
            self._expire(hid, survey, attempts, now, report)
            return
        if now < not_before:
            return
        if now > not_after:
            if row["state"] == "waiting_cap":
                with self.store.write() as conn:
                    if self.store.handoff_state(conn, hid) == "waiting_cap":
                        self.store.set_handoff_state(conn, hid, "cap_suppressed", now_s, "weekly cap stayed full for the whole send window")
                        report.cap_suppressed += 1
                return
            if not attempts:
                with self.store.write() as conn:
                    if self.store.handoff_state(conn, hid) in ("scheduled",):
                        self.store.set_handoff_state(conn, hid, "expired_unsent", now_s, "send window closed before any attempt (outside send hours?)")
                        report.expired += 1
                return
            return  # in progress past the window: no new channels; wait for reactions or expiry
        if not self._in_send_hours(now, handoff):
            return

        open_attempts = [a for a in attempts if a["state"] in ("sent", "awaiting")]
        if open_attempts:
            self._maybe_move_on(hid, handoff, survey, open_attempts[-1], attempts, now, report)
            return

        if not attempts:
            self._send(hid, handoff, survey, channel_index=0, attempt=1, now=now, report=report, first=True)
            return

        last = attempts[-1]
        if last["state"] == "retry_scheduled" and parse_ist(last["scheduled_for"]) <= now:
            self._send(hid, handoff, survey, channel_index=last["channel_index"], attempt=last["delivery_attempt"] + 1, now=now, report=report, marker=last)
        elif last["state"] == "fallback_scheduled":
            self._send(hid, handoff, survey, channel_index=last["channel_index"] + 1, attempt=1, now=now, report=report, marker=last)

    # ---------- sending and reactions ----------

    def _send(self, hid: str, handoff: dict[str, Any], survey: dict[str, Any], *, channel_index: int, attempt: int, now: datetime,
              report: TickReport, first: bool = False, marker: dict[str, Any] | None = None) -> None:
        """Atomic check-and-claim, then the simulated send. One transaction decides everything."""
        order = handoff["channel_order"]
        now_s = format_ist(now)
        if channel_index >= len(order):
            with self.store.write() as conn:
                if self.store.handoff_state(conn, hid) in ACTIVE_STATES:
                    self._close_markers(conn, hid, now_s)
                    self.store.set_handoff_state(conn, hid, "undeliverable", now_s, "every channel in channel_order failed")
                    report.failed += 1
            return
        channel = order[channel_index]["channel"]
        key = self._attempt_key(hid, channel, attempt)
        # Defence in depth: the text that will be shown is re-validated at send time.
        problems = validate_survey_text(survey, survey.get("language", "en-IN"))
        reaction = self.simulator.react(survey, channel, attempt, now)
        with self.store.write() as conn:
            state = self.store.handoff_state(conn, hid)
            if state not in ACTIVE_STATES:
                return
            if problems:
                self._close_markers(conn, hid, now_s)
                self.store.set_handoff_state(conn, hid, "blocked_unsafe", now_s, "survey text failed the content policy: " + ",".join(problems)[:200])
                report.blocked_unsafe += 1
                return
            if first:
                if conn.execute("SELECT 1 FROM delivery_attempts WHERE handoff_id = ? AND sent_at IS NOT NULL LIMIT 1", (hid,)).fetchone():
                    report.claims_lost += 1
                    return  # another worker already sent for this hand-off
                if self._cap_full(conn, handoff, now):
                    if state != "waiting_cap":
                        self.store.set_handoff_state(conn, hid, "waiting_cap", now_s, "weekly cap full; deferred")
                    report.cap_deferred_ticks += 1
                    return
            claimed = self.store.claim_attempt(conn, {
                "attempt_key": key, "handoff_id": hid, "survey_id": survey["survey_id"], "channel": channel, "channel_index": channel_index,
                "delivery_attempt": attempt, "state": "awaiting", "scheduled_for": now_s, "sent_at": now_s, "outcome_status": None,
                "failure_code": None, "response_key": None, "created_at": now_s, "updated_at": now_s,
            })
            if not claimed:
                report.claims_lost += 1
                return
            if marker is not None:
                conn.execute("UPDATE delivery_attempts SET state = 'superseded', updated_at = ? WHERE attempt_key = ? AND state IN ('retry_scheduled', 'fallback_scheduled')",
                             (now_s, marker["attempt_key"]))
            conn.execute("INSERT INTO kv (k, v) VALUES (?, ?) ON CONFLICT (k) DO UPDATE SET v = excluded.v",
                         (f"reaction:{key}", json.dumps({"outcome": reaction.outcome, "delay_minutes": reaction.delay_minutes, "record": reaction.record}, ensure_ascii=False)))
            self.store.set_handoff_state(conn, hid, "in_progress", now_s, f"sent on {channel} (attempt {attempt})")
            self.store.audit(conn, now_s, "delivery", key, "sent", {"channel": channel, "attempt": attempt, "simulated": True})
        report.sent += 1

    def _materialise_reactions(self, hid: str, survey: dict[str, Any], attempts: list[dict[str, Any]], now: datetime, report: TickReport) -> None:
        for a in attempts:
            if a["state"] != "awaiting":
                continue
            raw = self.store.kv_get(f"reaction:{a['attempt_key']}")
            if not raw:
                continue
            reaction = json.loads(raw)
            if reaction["record"] is None:
                continue  # silent: handled by wait_hours / expiry
            due = parse_ist(a["sent_at"]) + timedelta(minutes=int(reaction["delay_minutes"]))
            if due > now:
                continue
            self._apply_record(hid, survey, a, reaction["record"], now, report)

    def _apply_record(self, hid: str, survey: dict[str, Any], attempt: dict[str, Any], record: dict[str, Any], now: datetime, report: TickReport) -> None:
        now_s = format_ist(now)
        status = record["status"]
        code = record.get("failure_code")
        with self.store.write() as conn:
            current = conn.execute("SELECT state FROM delivery_attempts WHERE attempt_key = ?", (attempt["attempt_key"],)).fetchone()
            if current is None or current["state"] != "awaiting":
                return  # another worker applied this reaction already
            if status in SUCCESS_STATUSES and self.store.survey_has_accepted_answer(conn, survey["survey_id"]):
                dup = dict(record)
                dup.update({"response_key": f"{record['response_key']}-dup"[:64], "status": "duplicate", "failure_code": "duplicate_answer",
                            "answers": {}, "complete": False, "retry_decision": "none", "retry_after_minutes": None, "counts_toward_cap": False,
                            "farmerchat_reply": {"http_status": 200, "outcome": "duplicate"}, "needs_follow_up": False, "follow_up_reasons": [],
                            "items": [{**i, "result": "discarded" if i["result"] == "answered" else i["result"]} for i in record["items"]]})
                self._store_response(conn, dup, report)
                self._finish_attempt(conn, attempt, "duplicate", dup, now_s)
                report.duplicates_ignored += 1
                return
            stored = self._store_response(conn, record, report)
            if not stored and self.store.get_response(record["response_key"]) is None:
                return  # schema-invalid record: leave the attempt awaiting; noted in report
            if record["counts_toward_cap"]:
                conn.execute("UPDATE handoffs SET counted_at = ? WHERE handoff_id = ? AND counted_at IS NULL", (record["timestamps"]["sent"] or now_s, hid))
            if status in SUCCESS_STATUSES:
                self._finish_attempt(conn, attempt, "answered", record, now_s)
                self._close_markers(conn, hid, now_s)
                self.store.set_handoff_state(conn, hid, "answered", now_s, f"{status} on {record['channel']}" + (" (needs follow-up)" if record["needs_follow_up"] else ""))
                report.answered += 1
                return
            if code == "farmer_opted_out":
                conn.execute("INSERT INTO kv (k, v) VALUES (?, ?) ON CONFLICT (k) DO UPDATE SET v = excluded.v", (f"optout:{survey['farmer_id']}", "1"))
            decision = record["retry_decision"]
            self._finish_attempt(conn, attempt, "failed", record, now_s)
            report.failed += 1
            if decision == "retry_same_channel":
                if attempt["delivery_attempt"] >= self.settings.broadcaster_max_attempts_per_channel:
                    self._schedule_marker(conn, attempt, "fallback_scheduled", now_s)
                else:
                    due = now + timedelta(minutes=int(record["retry_after_minutes"] or 0))
                    self._schedule_marker(conn, attempt, "retry_scheduled", format_ist(due))
            elif decision == "fall_back_to_next_channel":
                self._schedule_marker(conn, attempt, "fallback_scheduled", now_s)
            else:  # give_up or none
                terminal = {"declined": "declined", "expired": "expired", "stale": "expired", "identity_mismatch": "undeliverable",
                            "invalid_input": "declined", "delivery_failed": "undeliverable", "duplicate": "answered"}.get(status, "undeliverable")
                self._close_markers(conn, hid, now_s)
                self.store.set_handoff_state(conn, hid, terminal, now_s, f"{status}/{code} on {record['channel']}")

    def _finish_attempt(self, conn, attempt: dict[str, Any], state: str, record: dict[str, Any], now_s: str) -> None:
        conn.execute("UPDATE delivery_attempts SET state = ?, outcome_status = ?, failure_code = ?, response_key = ?, updated_at = ? WHERE attempt_key = ?",
                     (state, record["status"], record.get("failure_code"), record["response_key"], now_s, attempt["attempt_key"]))
        conn.execute("DELETE FROM kv WHERE k = ?", (f"reaction:{attempt['attempt_key']}",))

    def _close_markers(self, conn, hid: str, now_s: str) -> None:
        conn.execute("UPDATE delivery_attempts SET state = 'closed', updated_at = ? WHERE handoff_id = ? AND state IN ('retry_scheduled', 'fallback_scheduled')",
                     (now_s, hid))

    def _schedule_marker(self, conn, attempt: dict[str, Any], marker: str, when: str) -> None:
        """Durable successor state, written in the same transaction as the attempt's outcome."""
        key = f"{attempt['attempt_key']}:next"
        self.store.upsert_attempt(conn, {
            "attempt_key": key, "handoff_id": attempt["handoff_id"], "survey_id": attempt["survey_id"], "channel": attempt["channel"],
            "channel_index": attempt["channel_index"], "delivery_attempt": attempt["delivery_attempt"], "state": marker, "scheduled_for": when,
            "sent_at": None, "outcome_status": None, "failure_code": None, "response_key": None, "created_at": when, "updated_at": when,
        })

    def _maybe_move_on(self, hid: str, handoff: dict[str, Any], survey: dict[str, Any], attempt: dict[str, Any], attempts: list[dict[str, Any]],
                       now: datetime, report: TickReport) -> None:
        """No reaction yet: after wait_hours record the fallback durably, then try the next channel."""
        order = handoff["channel_order"]
        step = order[attempt["channel_index"]]
        wait = step["wait_hours"]
        if wait is None:
            return  # last channel: wait for the farmer or expiry
        if parse_ist(attempt["sent_at"]) + timedelta(hours=int(wait)) > now:
            return
        next_index = attempt["channel_index"] + 1
        if next_index >= len(order) or any(a["channel_index"] == next_index for a in attempts):
            return
        now_s = format_ist(now)
        with self.store.write() as conn:
            cur = conn.execute("UPDATE delivery_attempts SET state = 'moved_on', updated_at = ? WHERE attempt_key = ? AND state = 'awaiting'",
                               (now_s, attempt["attempt_key"]))
            if cur.rowcount != 1:
                return  # someone else moved on already
            conn.execute("DELETE FROM kv WHERE k = ?", (f"reaction:{attempt['attempt_key']}",))
            self._schedule_marker(conn, attempt, "fallback_scheduled", now_s)  # survives a crash before the next send
        report.moved_on += 1
        marker = next(a for a in self.store.attempts_for_handoff(hid) if a["attempt_key"] == f"{attempt['attempt_key']}:next")
        self._send(hid, handoff, survey, channel_index=next_index, attempt=1, now=now, report=report, marker=marker)

    def _expire(self, hid: str, survey: dict[str, Any], attempts: list[dict[str, Any]], now: datetime, report: TickReport) -> None:
        now_s = format_ist(now)
        sent_any = any(a["sent_at"] for a in attempts)
        with self.store.write() as conn:
            if self.store.handoff_state(conn, hid) not in ACTIVE_STATES:
                return
            for a in attempts:
                if a["state"] not in ("awaiting", "moved_on"):
                    continue
                code = "push_not_opened" if a["channel"] == "app" else "window_expired"
                spec = self.codes.failure(code)
                record = self.simulator._failure_record(survey, a["channel"], a["delivery_attempt"], parse_ist(a["sent_at"]), code, spec, 0)
                record["recorded_at"] = now_s
                record["response_key"] = f"rk-{survey['survey_id']}-{a['channel']}-{a['delivery_attempt']}-{code}"[:64]
                if self._store_response(conn, record, report) and record["counts_toward_cap"]:
                    conn.execute("UPDATE handoffs SET counted_at = ? WHERE handoff_id = ? AND counted_at IS NULL", (a["sent_at"], hid))
                self._finish_attempt(conn, a, "expired", record, now_s)
            self._close_markers(conn, hid, now_s)
            self.store.set_handoff_state(conn, hid, "expired" if sent_any else "expired_unsent", now_s, "expires_at passed")
        report.expired += 1
