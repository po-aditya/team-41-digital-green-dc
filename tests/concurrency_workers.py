"""Worker functions for process-level concurrency tests (importable by multiprocessing 'spawn')."""

from __future__ import annotations

import json

from mel_agent.config import Settings
from mel_agent.delivery.clock import SimulatedClock
from mel_agent.delivery.simulator import ScriptedSimulator
from mel_agent.pipeline import Pipeline
from mel_agent.store import Store


def broadcaster_tick(db_path: str, clock_iso: str, script: dict, barrier, out_queue) -> None:
    """Open an independent connection, wait for every worker at the barrier, tick once."""
    settings = Settings(app_env="test", _env_file=None)
    pipeline = Pipeline(settings, Store(db_path), clock=SimulatedClock(clock_iso))
    pipeline.simulator = ScriptedSimulator(pipeline.outcome_codes, 1, dict(script))
    barrier.wait(timeout=30)
    report = pipeline.broadcaster().tick()
    out_queue.put({"sent": report.sent, "cap_deferred_ticks": report.cap_deferred_ticks, "claims_lost": report.claims_lost})


def generate_one(db_path: str, insight_id: str, barrier, out_queue) -> None:
    """Independent process tries to generate+schedule the same insight as its peers."""
    settings = Settings(app_env="test", _env_file=None)
    pipeline = Pipeline(settings, Store(db_path))
    barrier.wait(timeout=30)
    out = pipeline.process_insight(insight_id, "2026-11-01T00:00:00+05:30")
    out_queue.put(json.dumps(out.get("generation")))


def reserve_many(db_path: str, n: int, barrier, out_queue) -> None:
    """Independent process reserving budget concurrently with its peers."""
    from mel_agent.budget import BudgetController, BudgetExceeded
    from mel_agent.llm.pricing import ModelPrice, PricingTable

    settings = Settings(allow_paid_inference=True, budget_safety_factor=1.0, _env_file=None)
    ctl = BudgetController(Store(db_path), settings, PricingTable({"m": ModelPrice(input=1.0, output=1.0)}))
    barrier.wait(timeout=30)
    granted = 0
    for _ in range(n):
        try:
            ctl.reserve("m", 30_000_000, 0)  # $30 each
            granted += 1
        except BudgetExceeded:
            pass
    out_queue.put(granted)


class _SlowTemplate:
    """Template provider that sleeps before answering: a worker that outlives its lease."""

    name = "template"
    deterministic = True

    def __init__(self, sleep_s: float) -> None:
        import time

        from mel_agent.generation.providers import TemplateProvider

        self._inner, self._sleep, self._time = TemplateProvider(), sleep_s, time

    def generate(self, request, attempt):
        self._time.sleep(self._sleep)
        return self._inner.generate(request, attempt)


def generate_slow(db_path: str, insight_id: str, sleep_s: float, lease_s: int, started, out_queue) -> None:
    """Claim the insight with a short real-time lease, then take longer than the lease to generate."""
    from mel_agent.contracts import SchemaRegistry
    from mel_agent.generation.generator import SurveyGenerator

    settings = Settings(app_env="test", generation_lease_seconds=lease_s, _env_file=None)
    registry = SchemaRegistry(settings.schemas_dir)
    pipeline = Pipeline(settings, Store(db_path), registry)
    pipeline.generator = SurveyGenerator(settings, registry, _SlowTemplate(sleep_s), fallback=None)
    started.set()
    out = pipeline.process_insight(insight_id, "2026-11-01T00:00:00+05:30")
    out_queue.put(json.dumps(out.get("generation")))
