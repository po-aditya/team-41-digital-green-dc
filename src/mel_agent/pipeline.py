"""End-to-end orchestration: ingest → decide → generate → schedule → deliver.

Every stage is idempotent and persists its result before the next stage reads
it. An insight that is quarantined, suppressed, or whose survey fails
validation never produces a hand-off, so it can never be scheduled or sent.

Generation is protected by a durable claim per insight (table
``generation_claims``): concurrent workers, threads or processes, generate each
insight at most once, and a survey id can belong to exactly one insight.
Downstream stages refuse to run on an incomplete ingestion.
"""

from __future__ import annotations

import dataclasses

import json
import os
import socket
import threading
import time
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Iterable

from mel_agent.config import Settings
from mel_agent.contracts import SchemaName, SchemaRegistry
from mel_agent.data.ingest import IngestStats, Ingestor
from mel_agent.data.pack import OutcomeCodes, PackPaths, Rules, pack_paths
from mel_agent.delivery.broadcaster import Broadcaster
from mel_agent.delivery.clock import SimulatedClock
from mel_agent.delivery.simulator import Simulator
from mel_agent.generation.generator import SurveyGenerator
from mel_agent.generation.models import SurveyProvider, SurveyRequest
from mel_agent.rules.eligibility import CropCalendar, Decision, Outcome, decide
from mel_agent.rules.scheduling import build_handoff, survey_id_for
from mel_agent.store import Store
from mel_agent.time_utils import format_ist, parse_ist


class PipelineError(RuntimeError):
    pass


class IngestionIncomplete(PipelineError):
    """The latest ingestion did not finish; downstream stages refuse to run on partial data."""


def _rejection_problems(result) -> list[str]:
    """Problem codes for a rejected generation: the safety report's, else the last attempt's, else provider_failed."""
    if result.safety is not None and result.safety.problems:
        return list(result.safety.problems)
    for attempt in reversed(result.attempts):
        if attempt.get("problems"):
            return list(attempt["problems"])
    return ["provider_failed"]


class ClaimLost(PipelineError):
    """Another worker took over this insight's generation claim; nothing was persisted by this one."""


@dataclass
class StageStats:
    processed: int = 0
    surveys_accepted: int = 0
    surveys_rejected: int = 0
    handoffs_created: int = 0
    skipped_existing: int = 0
    skipped_not_eligible: int = 0
    skipped_busy: int = 0
    id_collisions: int = 0
    pending_approval: int = 0
    lost_claims: int = 0
    generation_sources: dict[str, int] = field(default_factory=dict)
    rejection_problems: dict[str, int] = field(default_factory=dict)
    elapsed_s: float = 0.0
    per_survey_ms: list[float] = field(default_factory=list)
    usage: dict[str, Any] = field(default_factory=dict)
    estimated_cost_usd: float = 0.0
    failed_attempt_cost_usd: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        d = self.__dict__.copy()
        ms = sorted(self.per_survey_ms)
        d.pop("per_survey_ms")
        d["generation_latency_ms"] = {
            "count": len(ms), "mean": round(sum(ms) / len(ms), 3) if ms else None,
            "p50": round(ms[len(ms) // 2], 3) if ms else None, "p95": round(ms[int(len(ms) * 0.95) - 1 if len(ms) >= 20 else -1], 3) if ms else None,
            "max": round(ms[-1], 3) if ms else None,
        }
        d["elapsed_s"] = round(self.elapsed_s, 3)
        return d


def worker_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}:{threading.get_ident()}"


class Pipeline:
    def __init__(self, settings: Settings, store: Store, registry: SchemaRegistry | None = None,
                 provider: SurveyProvider | None = None, clock: SimulatedClock | None = None, simulator: Simulator | None = None) -> None:
        self.settings = settings
        self.store = store
        self.paths: PackPaths = pack_paths(settings).require()
        self.registry = registry or SchemaRegistry(settings.schemas_dir)
        self.rules = Rules.load(self.paths)
        self.outcome_codes = OutcomeCodes.load(self.paths)
        self.generator = SurveyGenerator(settings, self.registry, provider)
        self.clock = clock or SimulatedClock("2026-11-01T00:00:00+05:30")
        self.simulator = simulator or Simulator(self.outcome_codes, settings.simulation_seed)
        self._calendar: CropCalendar | None = None

    # ---------- stage 1: ingest ----------

    def ingest(self, now: str) -> IngestStats:
        stats = Ingestor(self.store, self.registry, self.paths).run(now)
        self._calendar = None
        return stats

    def require_complete_ingestion(self) -> None:
        if not self.store.ingestion_complete():
            raise IngestionIncomplete("the latest ingestion did not complete; re-run ingest before deciding or generating")

    @property
    def calendar(self) -> CropCalendar:
        """Crop calendar from the store, or straight from the pack CSV before any ingestion."""
        if self._calendar is None:
            rows = self.store.calendar_rows()
            if not rows:
                import csv

                with self.paths.crop_calendar_csv.open(encoding="utf-8", newline="") as fh:
                    rows = [r for r in csv.DictReader(fh) if r.get("crop") and r.get("end_date")]
            self._calendar = CropCalendar.from_rows(rows)
        return self._calendar

    # ---------- stage 2: decide ----------

    def decide_one(self, row: dict[str, Any]) -> Decision:
        insight = json.loads(row["raw_json"]) if isinstance(row.get("raw_json"), str) else row
        if not isinstance(insight, dict):
            insight = {"insight_id": row.get("insight_id"), "farmer_id": row.get("farmer_id")}
        return decide(insight, self.rules, self.calendar, schema_valid=bool(row.get("schema_valid", 1)),
                      farmer_known=row.get("quarantine_reason") != "unknown_farmer")

    def decide_all(self, now: str, run_id: str | None = None, limit: int | None = None) -> dict[str, Any]:
        self.require_complete_ingestion()
        started = time.perf_counter()
        counts: dict[str, int] = {}
        n = 0
        with self.store.write() as conn:
            for row in list(self.store.iter_insights(only_valid=False)):
                if limit is not None and n >= limit:
                    break
                d = self.decide_one(row)
                rec = d.to_record()
                self.store.upsert_decision(conn, {**rec, "details_json": json.dumps(rec["details"], sort_keys=True), "decided_at": now, "run_id": run_id})
                counts[d.reason.value] = counts.get(d.reason.value, 0) + 1
                n += 1
        return {"decided": n, "by_internal_reason": counts, "elapsed_s": round(time.perf_counter() - started, 3)}

    # ---------- stage 3+4: generate and schedule ----------

    def _language_for(self, insight: dict[str, Any], override: str | None) -> str:
        return override or insight.get("conversation_language") or "en-IN"

    def generate_and_schedule(self, now: str, *, insight_ids: Iterable[str] | None = None, limit: int | None = None,
                              language: str | None = None) -> StageStats:
        """For every insight with a survey decision and no hand-off yet: claim, generate, validate, hand off."""
        self.require_complete_ingestion()
        started = time.perf_counter()
        stats = StageStats()
        page_ids = [r["insight_id"] for r in self._survey_decision_ids()] if insight_ids is None else list(insight_ids)
        for insight_id in page_ids:
            if limit is not None and stats.processed >= limit:
                break
            decision_row = self.store.get_decision(insight_id)
            if decision_row is None or decision_row["decision"] != Outcome.SURVEY.value:
                stats.skipped_not_eligible += 1
                continue
            survey_id = survey_id_for(insight_id)
            existing = self.store.get_survey(survey_id)
            if existing is not None and existing["insight_id"] != insight_id:
                stats.id_collisions += 1  # the survey id already belongs to another insight: never reuse it
                continue
            if self.store.get_handoff_for_survey(survey_id) is not None:
                stats.skipped_existing += 1
                continue
            outcome = self._generate_one(insight_id, survey_id, now, language, stats)
            if outcome["status"] in ("busy", "already_scheduled"):
                stats.skipped_busy += outcome["status"] == "busy"
                stats.skipped_existing += outcome["status"] == "already_scheduled"
                continue
            if outcome["status"] == "id_collision":
                stats.id_collisions += 1
                continue
            if outcome["status"] == "lost_claim":
                stats.lost_claims += 1
                continue
            stats.processed += 1
        stats.elapsed_s = time.perf_counter() - started
        return stats

    def _survey_decision_ids(self) -> list[dict[str, Any]]:
        with self.store.read() as conn:
            return [dict(r) for r in conn.execute("SELECT insight_id FROM decisions WHERE decision = 'survey' ORDER BY insight_id")]

    def _generate_one(self, insight_id: str, survey_id: str, now: str, language: str | None, stats: StageStats) -> dict[str, Any]:
        row = self.store.get_insight(insight_id)
        if row is None:
            return {"status": "unknown_insight", "insight_id": insight_id}
        insight = json.loads(row["raw_json"])
        decision = self.decide_one(row)
        if not decision.survey or decision.send_window is None:
            stats.skipped_not_eligible += 1
            return {"status": "not_eligible", "reason": decision.reason.value}

        # Durable claim: one generation per insight, one insight per survey id, owned by a fencing
        # token with a real-time lease (simulated season time never expires it).
        owner = worker_id()
        lease = self.settings.generation_lease_seconds
        with self.store.write() as conn:
            claim, token = self.store.claim_generation(conn, insight_id, survey_id, owner, now, lease_seconds=lease)
            if claim == "collision":
                self.store.audit(conn, now, "insight", insight_id, "survey_id_collision", {"survey_id": survey_id})
        if claim == "collision":
            return {"status": "id_collision", "survey_id": survey_id}
        if claim == "done":
            return {"status": "already_scheduled", "survey_id": survey_id}
        if claim == "busy":
            return {"status": "busy", "survey_id": survey_id}

        try:
            return self._generate_claimed(insight_id, survey_id, insight, decision, now, language, stats, token)
        except ClaimLost:
            return {"status": "lost_claim", "survey_id": survey_id}
        except BaseException:
            with self.store.write() as conn:
                self.store.finish_claim(conn, insight_id, token, "failed", now)
            raise

    def _generate_claimed(self, insight_id: str, survey_id: str, insight: dict[str, Any], decision: Decision, now: str,
                          language: str | None, stats: StageStats, token: str) -> dict[str, Any]:
        farmer = self.store.get_farmer(insight["farmer_id"])
        lang = self._language_for(insight, language)
        request = SurveyRequest.build(survey_id, insight, json.loads(farmer["raw_json"]) if farmer else None, lang,
                                      decision.send_window, self.rules.asks_for_resolution(insight["resolution_type"]))
        # Ownership check used before EVERY model invocation (first attempt, retries, fallback): it extends the
        # lease and fails once another worker has taken the claim over, so a superseded worker never starts a
        # new paid request. A request already in flight when the lease lapses still completes and is accounted.
        def still_owner() -> bool:
            with self.store.write() as conn:
                return self.store.heartbeat_claim(conn, insight_id, token, self.settings.generation_lease_seconds)

        request = dataclasses.replace(request, may_continue=still_owner)
        if not still_owner():
            raise ClaimLost(insight_id)
        t0 = time.perf_counter()
        result = self.generator.generate(request)
        if result.aborted:
            raise ClaimLost(insight_id)
        stats.per_survey_ms.append((time.perf_counter() - t0) * 1000)
        stats.generation_sources[result.source] = stats.generation_sources.get(result.source, 0) + 1
        for k, v in result.usage.items():
            stats.usage[k] = stats.usage.get(k, 0) + v
        stats.estimated_cost_usd += result.estimated_cost_usd
        stats.failed_attempt_cost_usd += result.failed_attempt_cost_usd
        validation = result.to_dict()
        validation["injection_suspected"] = request.untrusted_text_flags
        status = "validated" if result.accepted else "rejected"
        if result.accepted and result.requires_approval:
            status = "pending_approval"  # free-form wording: a human must approve; never scheduled here
        with self.store.write() as conn:
            # Fencing: everything below happens only if this worker still owns the claim. The claim is
            # moved out of 'generating' first, so a late twin cannot finalise after us either.
            if not self.store.finish_claim(conn, insight_id, token, "done" if status == "validated" else "failed", now):
                raise ClaimLost(insight_id)
            written = self.store.upsert_survey(conn, {
                "survey_id": survey_id, "insight_id": insight_id, "farmer_id": insight["farmer_id"], "language": lang, "status": status,
                "generation_source": result.source, "attempts": len(result.attempts),
                "survey_json": json.dumps(result.survey, ensure_ascii=False, sort_keys=True) if result.survey else None,
                "validation_json": json.dumps(validation, ensure_ascii=False, sort_keys=True),
                "timing_json": json.dumps(decision.send_window.to_dict(), sort_keys=True), "created_at": now,
            })
            self.store.audit(conn, now, "survey", survey_id, f"generation:{status}", {"source": result.source, "attempts": len(result.attempts)})
            if not written:
                return {"status": "already_scheduled", "survey_id": survey_id}
            if status == "pending_approval":
                stats.pending_approval += 1  # audited above as generation:pending_approval
                return {"status": "pending_approval", "survey_id": survey_id}
            if not result.accepted:
                stats.surveys_rejected += 1
                problems = _rejection_problems(result)
                for p in problems:
                    stats.rejection_problems[p] = stats.rejection_problems.get(p, 0) + 1
                return {"status": "rejected", "survey_id": survey_id, "problems": problems}
            stats.surveys_accepted += 1
            handoff = build_handoff(insight, result.survey, decision.send_window, self.rules)
            errors = self.registry.errors(SchemaName.SCHEDULE_HANDOFF, handoff)
            if errors:
                conn.execute("UPDATE surveys SET status = 'handoff_invalid' WHERE survey_id = ?", (survey_id,))
                self.store.audit(conn, now, "survey", survey_id, "handoff_invalid", {"first_error": f"{errors[0].path}: {errors[0].validator}"})
                return {"status": "handoff_invalid", "survey_id": survey_id}
            created = self.store.insert_handoff(conn, {
                "handoff_id": handoff["handoff_id"], "survey_id": survey_id, "farmer_id": insight["farmer_id"], "priority": handoff["priority"],
                "not_before": handoff["send_window"]["not_before"], "not_after": handoff["send_window"]["not_after"],
                "expires_at": handoff["expires_at"], "state": "scheduled", "state_detail": None, "counted_at": None,
                "handoff_json": json.dumps(handoff, ensure_ascii=False, sort_keys=True), "created_at": now, "updated_at": now,
            })
            if created:
                self.store.audit(conn, now, "handoff", handoff["handoff_id"], "state:scheduled", {"priority": handoff["priority"]})
                stats.handoffs_created += 1
        return {"status": "scheduled", "survey_id": survey_id, "handoff_id": handoff["handoff_id"]}

    def process_insight(self, insight_id: str, now: str, language: str | None = None) -> dict[str, Any]:
        """Run decide → generate → schedule for one insight (used by demos and the API).

        Refuses, like every other generation entry point, when the latest ingestion is not complete:
        a partially imported dataset must never be mistaken for a complete one."""
        self.require_complete_ingestion()
        row = self.store.get_insight(insight_id)
        if row is None:
            return {"status": "unknown_insight", "insight_id": insight_id}
        decision = self.decide_one(row)
        rec = decision.to_record()
        with self.store.write() as conn:
            self.store.upsert_decision(conn, {**rec, "details_json": json.dumps(rec["details"], sort_keys=True), "decided_at": now, "run_id": None})
        out: dict[str, Any] = {"status": "decided", "insight_id": insight_id, "decision": rec}
        if decision.outcome is Outcome.NO_SURVEY:
            out["no_survey"] = decision.to_no_survey_contract()
            out["no_survey_schema_valid"] = not self.registry.errors(SchemaName.NO_SURVEY, out["no_survey"])
            return out
        if decision.outcome is Outcome.QUARANTINED:
            return out
        survey_id = survey_id_for(insight_id)
        existing = self.store.get_survey(survey_id)
        if existing is not None and existing["insight_id"] != insight_id:
            out["generation"] = {"status": "id_collision", "survey_id": survey_id}
            return out
        if self.store.get_handoff_for_survey(survey_id) is not None:
            out["generation"] = {"status": "already_scheduled", "survey_id": survey_id}
            return out
        stats = StageStats()
        out["generation"] = self._generate_one(insight_id, survey_id, now, language, stats)
        return out

    # ---------- stage 5: deliver ----------

    def broadcaster(self) -> Broadcaster:
        return Broadcaster(self.store, self.rules, self.outcome_codes, self.registry, self.settings, self.clock, self.simulator)

    def run_broadcaster(self, until: str, step_minutes: int = 60) -> dict[str, Any]:
        reports = self.broadcaster().run_until(until, step_minutes)  # validates step, direction and tick count
        totals: dict[str, int] = {}
        for r in reports:
            for k, v in r.to_dict().items():
                if isinstance(v, int):
                    totals[k] = totals.get(k, 0) + v
        return {"ticks": len(reports), "from": reports[0].at if reports else None, "to": reports[-1].at if reports else None,
                "totals": totals, "notes": [n for r in reports for n in r.notes][:50]}

    # ---------- summaries ----------

    def summary(self) -> dict[str, Any]:
        run = self.store.latest_ingest_run()
        return {
            "ingestion": {"status": run["status"], **run["stats"]} if run else None,
            "decisions": self.store.decision_counts(),
            "surveys": self.store.survey_counts(),
            "handoffs": self.store.handoff_counts(),
            "delivery_attempts": self.store.attempt_counts(),
            "responses": self.store.response_counts(),
            "clock": format_ist(self.clock.now),
        }
