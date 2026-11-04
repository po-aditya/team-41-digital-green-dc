"""Regression tests for the THIRD independent (Codex) review of commit 75a09a67.

One class per finding, in the review's order. Each class starts with the reviewer's
reproduction (``test_codex_reproduction_*``) and continues with adversarial variants.
Every reproduction fails on the 75a09a67 baseline.

Nothing here reaches AWS: boto3 clients are built with fake credentials, their
``converse`` method is replaced, and the autouse ``no_network`` guard applies.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import threading
import time
from pathlib import Path

import boto3
import pytest
from botocore.config import Config
from botocore.exceptions import ClientError, ReadTimeoutError

from mel_agent.budget import BudgetController, BudgetExceeded, BudgetUnavailable, PaidInferenceDisabled
from mel_agent.config import Settings
from mel_agent.llm.pricing import ModelPrice, PricingTable, TokenUsage
from mel_agent.rules.scheduling import survey_id_for
from mel_agent.store import Store

NOW = "2026-11-01T00:00:00+05:30"
EARLIER = "2026-10-15T00:00:00+05:30"
MODEL = "m-test"
PRICING = PricingTable({MODEL: ModelPrice(input=1.0, output=2.0)})


def _settings(**over) -> Settings:
    base = {"allow_paid_inference": True, "budget_safety_factor": 1.0, "bedrock_model_id": MODEL, "bedrock_region": "us-west-2", "_env_file": None}
    base.update(over)
    return Settings(**base)


def _client(total_max_attempts: int | None = 1):
    cfg = Config(retries={"total_max_attempts": total_max_attempts}) if total_max_attempts is not None else None
    return boto3.client("bedrock-runtime", region_name="us-west-2", aws_access_key_id="testing", aws_secret_access_key="testing", config=cfg)


def _response(inp=1000, out=500, retry_attempts=0, usage=True, meta=True):
    r = {"output": {"message": {"role": "assistant", "content": [{"text": "ok"}]}}, "stopReason": "end_turn", "metrics": {"latencyMs": 5}}
    if meta:
        r["ResponseMetadata"] = {"RetryAttempts": retry_attempts, "HTTPStatusCode": 200}
    if usage:
        r["usage"] = {"inputTokens": inp, "outputTokens": out, "totalTokens": inp + out}
    return r


def _client_error(code: str, retry_attempts=0) -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": "x"}, "ResponseMetadata": {"RetryAttempts": retry_attempts, "HTTPStatusCode": 500}}, "Converse")


def _kinds(ctl: BudgetController) -> list[str]:
    return [row["kind"] for row in sorted(ctl.ledger(), key=lambda r: (r["created_at"], r["entry_id"]))]


def _eligible_insight(store: Store, **props):
    for row in store.iter_insights(only_valid=True):
        obj = json.loads(row["raw_json"])
        if (obj.get("verification") or {}).get("needed") and obj.get("severity") not in ("critical",) and obj.get("resolution_type") == "direct_action" \
                and all(obj.get(k) == v for k, v in props.items()):
            return obj
    raise AssertionError("no eligible insight")


def _invoker(tmp_path, client, **over):
    from mel_agent.llm.bedrock import BedrockInvoker
    from mel_agent.llm.budgeted import BudgetedInvoker

    settings = _settings(**{k: v for k, v in over.items() if k.startswith(("bedrock", "budget"))})
    ctl = BudgetController(Store(tmp_path / "b.db"), settings, PRICING)
    inv = BudgetedInvoker(BedrockInvoker(settings, pricing=PRICING, client=client), ctl,
                          **{k: v for k, v in over.items() if k in ("app_attempts", "retry_after_timeout")})
    return inv, ctl


def _raising(exc):
    def _f(**_k):
        raise exc
    return _f


# =====================================================================================
# F1 (HIGH)  Model-processing errors released reservations
# =====================================================================================

class TestF1ErrorClassification:
    def test_codex_reproduction_model_error_keeps_the_reservation_committed(self, tmp_path):
        """Reviewer: a ModelErrorException released the reservation and recorded $0. The error happens
        during model processing, so the attempt may well have been billed."""
        client = _client()
        client.converse = _raising(_client_error("ModelErrorException"))
        inv, ctl = _invoker(tmp_path, client)
        with pytest.raises(ClientError):
            inv.converse("hi", max_tokens=1000)
        s = ctl.status()
        assert s.unresolved_count == 1 and s.committed_usd > 0 and "release" not in _kinds(ctl)

    def test_codex_reproduction_string_retry_attempts_is_not_treated_as_zero(self, tmp_path):
        """Reviewer: RetryAttempts "2" (a string) was read as 0 and a throttle was released."""
        client = _client()
        client.converse = _raising(_client_error("ThrottlingException", retry_attempts="2"))
        inv, ctl = _invoker(tmp_path, client, app_attempts=3)
        with pytest.raises(ClientError):
            inv.converse("hi", max_tokens=100)
        assert _kinds(ctl) == ["reserve", "unresolved"]  # and no second attempt

    @pytest.mark.parametrize("bad", ["0", "2", True, False, -1, 1.5, None, [], {}])
    def test_malformed_retry_metadata_on_success_is_unresolved(self, tmp_path, bad):
        client = _client()
        client.converse = lambda **_k: _response(inp=10, out=1, retry_attempts=bad)
        inv, ctl = _invoker(tmp_path, client)
        result = inv.converse("hi", max_tokens=100_000)
        s = ctl.status()
        assert s.calls_settled == 0 and s.unresolved_count == 1 and result.estimated_cost_usd == pytest.approx(s.committed_usd, abs=1e-6)

    def test_absent_metadata_is_unknown_and_stays_unresolved(self, tmp_path):
        """botocore always sets RetryAttempts on a real response; a response without it is unverifiable, so the
        reservation stays committed (review-4 finding 1 reversed the earlier lenient reading)."""
        client = _client()
        client.converse = lambda **_k: _response(meta=False)
        inv, ctl = _invoker(tmp_path, client)
        inv.converse("hi", max_tokens=100)
        assert _kinds(ctl) == ["reserve", "unresolved"]

    @pytest.mark.parametrize("code", ["ModelErrorException", "ModelTimeoutException", "ModelStreamErrorException", "InternalServerException",
                                      "ServiceUnavailableException", "SomethingNewException", ""])
    def test_processing_and_unknown_errors_are_unresolved_and_stop_the_loop(self, tmp_path, code):
        client = _client()
        n = {"calls": 0}

        def fail(**_k):
            n["calls"] += 1
            raise _client_error(code)

        client.converse = fail
        inv, ctl = _invoker(tmp_path, client, app_attempts=3)
        with pytest.raises(ClientError):
            inv.converse("hi", max_tokens=100)
        assert n["calls"] == 1 and _kinds(ctl) == ["reserve", "unresolved"]

    @pytest.mark.parametrize("code,retry", [("ThrottlingException", True), ("TooManyRequestsException", True), ("ServiceQuotaExceededException", True),
                                            ("ModelNotReadyException", True), ("ValidationException", False), ("AccessDeniedException", False),
                                            ("ResourceNotFoundException", False), ("ExpiredTokenException", False)])
    def test_definitive_pre_inference_rejections_are_released(self, tmp_path, code, retry):
        from mel_agent.llm.budgeted import PaidCallFailed

        client = _client()
        n = {"calls": 0}

        def fail(**_k):
            n["calls"] += 1
            raise _client_error(code)

        client.converse = fail
        inv, ctl = _invoker(tmp_path, client, app_attempts=2)
        with pytest.raises((ClientError, PaidCallFailed)):
            inv.converse("hi", max_tokens=100)
        assert n["calls"] == (2 if retry else 1)
        assert _kinds(ctl) == ["reserve", "release"] * n["calls"] and ctl.status().committed_usd == 0

    def test_classification_policy_table(self):
        from mel_agent.llm.budgeted import RELEASE_PERMANENT, RELEASE_RETRYABLE, UNRESOLVED_EXAMPLES, classify_client_error

        assert not (RELEASE_RETRYABLE & RELEASE_PERMANENT) and not (UNRESOLVED_EXAMPLES & (RELEASE_RETRYABLE | RELEASE_PERMANENT))
        for code in RELEASE_RETRYABLE:
            assert classify_client_error(code, 0) == "release_retry" and classify_client_error(code, 1) == "unresolved" and classify_client_error(code, None) == "unresolved"
        for code in RELEASE_PERMANENT:
            assert classify_client_error(code, 0) == "release_stop" and classify_client_error(code, 2) == "unresolved"
        for code in UNRESOLVED_EXAMPLES | {"", "Whatever"}:
            assert classify_client_error(code, 0) == "unresolved"

    def test_unresolved_cap_blocks_new_paid_attempts_until_reconciled(self, tmp_path):
        client = _client()
        client.converse = _raising(ReadTimeoutError(endpoint_url="https://bedrock"))
        inv, ctl = _invoker(tmp_path, client, budget_max_unresolved=2)
        for _ in range(2):
            with pytest.raises(ReadTimeoutError):
                inv.converse("hi", max_tokens=100)
        reached = {"n": 0}
        client.converse = lambda **_k: reached.__setitem__("n", reached["n"] + 1) or _response()
        with pytest.raises(BudgetUnavailable, match="unresolved"):
            inv.converse("hi", max_tokens=100)
        assert reached["n"] == 0 and ctl.status().unresolved_count == 2
        # Reconciling one brings the count under the cap; the next attempt is allowed again.
        rid = ctl.unresolved()[0]["reservation_id"]
        ctl.reconcile(rid, 0.01, "bill")
        inv.converse("hi", max_tokens=100)
        assert reached["n"] == 1 and ctl.status().calls_settled == 2

    def test_unresolved_cap_survives_restart(self, tmp_path):
        settings = _settings(budget_max_unresolved=1)
        ctl = BudgetController(Store(tmp_path / "b.db"), settings, PRICING)
        ctl.mark_unresolved(ctl.reserve(MODEL, 1000, 10), "timeout")
        again = BudgetController(Store(tmp_path / "b.db"), settings, PRICING)
        with pytest.raises(BudgetUnavailable, match="unresolved"):
            again.reserve(MODEL, 1, 1)
        with pytest.raises(BudgetUnavailable, match="unresolved"):
            again.check_headroom(MODEL, 1, 1)

    def test_application_retry_after_timeout_reserves_again_and_both_stay_committed(self, tmp_path):
        client = _client()
        client.converse = _raising(ReadTimeoutError(endpoint_url="https://bedrock"))
        inv, ctl = _invoker(tmp_path, client, app_attempts=2, retry_after_timeout=True, budget_max_unresolved=5)
        with pytest.raises(ReadTimeoutError):
            inv.converse("hi", max_tokens=100)
        assert _kinds(ctl) == ["reserve", "unresolved", "reserve", "unresolved"]
        assert ctl.status().unresolved_count == 2 and ctl.status().committed_usd == pytest.approx(2 * float(ctl.estimate_cost(MODEL, ctl.estimate_tokens("hi"), 100)))


# =====================================================================================
# F2 (HIGH)  A failed import could overwrite active data
# =====================================================================================

def _mini_pack(root: Path, settings, insights: list[dict], golden_text: str | None = None) -> Path:
    from mel_agent.data.pack import pack_paths

    src = pack_paths(settings)
    if root.exists():
        shutil.rmtree(root)
    (root / "data").mkdir(parents=True)
    (root / "json" / "rules").mkdir(parents=True)
    shutil.copytree(src.schemas_dir, root / "json" / "schemas")
    for f in (src.rules_json, src.outcome_codes_json):
        shutil.copy(f, root / "json" / "rules" / f.name)
    shutil.copy(src.crop_calendar_csv, root / "data" / "crop_calendar_bihar_rabi.csv")
    shutil.copy(src.farmers_csv, root / "data" / "farmers.csv")
    (root / "data" / "insights.jsonl").write_text("".join(json.dumps(i, ensure_ascii=False) + "\n" for i in insights), encoding="utf-8")
    if golden_text is not None:
        (root / "data" / "golden_set.jsonl").write_text(golden_text, encoding="utf-8")
    return root


class TestF2AtomicIngestion:
    @pytest.fixture
    def mini(self, pipeline, settings, registry, tmp_path):
        """A pipeline over a one-insight pack, with the insight taken from the real dataset."""
        from mel_agent.delivery.clock import SimulatedClock
        from mel_agent.pipeline import Pipeline

        original = _eligible_insight(pipeline.store, preferred_channel="whatsapp")
        root = _mini_pack(tmp_path / "pack", settings, [original])
        store = Store(tmp_path / "mini.db")
        p = Pipeline(settings.model_copy(update={"participant_pack_dir": root}), store, registry, clock=SimulatedClock(NOW))
        assert p.ingest(NOW).insights_stored_valid == 1
        return p, root, original

    @staticmethod
    def _changed(original: dict) -> dict:
        changed = json.loads(json.dumps(original))
        changed["advice_summary"] = "REPLACEMENT RECORD: " + (original.get("advice_summary") or "")
        changed["asset"] = dict(changed["asset"], name="wheat" if changed["asset"].get("name") != "wheat" else "potato")
        return changed

    def test_codex_reproduction_backdated_failed_import_does_not_touch_the_active_dataset(self, mini, settings):
        """Reviewer: a second import with an EARLIER simulated time overwrote an insight, then failed on malformed
        golden JSONL; the first run still looked 'complete' and generation used the replacement record."""
        from mel_agent.data.ingest import IngestError

        p, root, original = mini
        first = p.store.latest_ingest_run()
        changed = self._changed(original)
        _mini_pack(root, settings, [changed], golden_text='{"insight_id": "I-000001", not json\n')
        with pytest.raises(IngestError):
            p.ingest(EARLIER)
        # The active dataset is the FIRST run's, byte for byte; the failed run is recorded and is the latest executed.
        assert p.store.ingestion_complete() is False  # the latest EXECUTED run failed: generation is blocked, not misled
        row = p.store.get_insight(original["insight_id"])
        assert json.loads(row["raw_json"]) == original and row["run_id"] == first["run_id"]
        latest = p.store.latest_ingest_run()
        assert latest["status"] == "failed" and latest["started_at"] == EARLIER and latest["seq"] == first["seq"] + 1
        from mel_agent.pipeline import IngestionIncomplete

        with pytest.raises(IngestionIncomplete):
            p.process_insight(original["insight_id"], NOW)
        # A good re-import of the ORIGINAL pack restores service on the original record.
        _mini_pack(root, settings, [original])
        p.ingest(NOW)
        out = p.process_insight(original["insight_id"], NOW)
        assert out["generation"]["status"] == "scheduled"
        hj = json.loads(p.store.get_handoff(out["generation"]["handoff_id"])["handoff_json"])
        assert "REPLACEMENT" not in json.dumps(hj) and json.loads(p.store.get_insight(original["insight_id"])["raw_json"]) == original

    def test_simulated_time_never_decides_which_run_is_current(self, mini, settings):
        p, root, original = mini
        first = p.store.latest_ingest_run()
        changed = self._changed(original)
        _mini_pack(root, settings, [changed])
        stats = p.ingest(EARLIER)  # a successful backdated import IS the newest dataset
        assert stats.insights_stored_valid == 1
        latest = p.store.latest_ingest_run()
        assert latest["run_id"] != first["run_id"] and latest["seq"] == first["seq"] + 1 and latest["started_at"] == EARLIER
        assert p.store.ingestion_complete() and json.loads(p.store.get_insight(original["insight_id"])["raw_json"]) == changed
        assert p.store.get_insight(original["insight_id"])["run_id"] == latest["run_id"]

    def test_failure_after_partial_staging_changes_nothing(self, pipeline, settings, registry, tmp_path, monkeypatch):
        from mel_agent.data.ingest import IngestError, Ingestor
        from mel_agent.data.pack import PackPaths

        rows = [json.loads(r["raw_json"]) for r in list(pipeline.store.iter_insights(only_valid=True))[:6]]
        root = _mini_pack(tmp_path / "pack", settings, rows)
        store = Store(tmp_path / "s.db")
        Ingestor(store, registry, PackPaths(root)).run(NOW)
        before = {r["insight_id"]: r["raw_json"] for r in store.iter_insights(only_valid=False)}
        changed = [dict(r, advice_summary="CHANGED " + str(i)) for i, r in enumerate(rows)]
        _mini_pack(root, settings, changed)
        real = Store.upsert_insight
        count = {"n": 0}

        def flaky(self, conn, row):
            count["n"] += 1
            if count["n"] == 4:
                raise RuntimeError("disk full")
            return real(self, conn, row)

        monkeypatch.setattr(Store, "upsert_insight", flaky)
        with pytest.raises(IngestError):
            Ingestor(store, registry, PackPaths(root)).run("2026-11-02T00:00:00+05:30")
        monkeypatch.undo()
        after = {r["insight_id"]: r["raw_json"] for r in store.iter_insights(only_valid=False)}
        assert after == before and count["n"] == 4  # three rows were staged and all rolled back
        assert not store.ingestion_complete() and store.latest_ingest_run()["error"] == "RuntimeError"
        with store.read() as conn:
            assert conn.execute("SELECT COUNT(*) FROM farmers").fetchone()[0] == 300  # farmers were re-staged and rolled back too, not lost

    def test_crash_between_data_and_status_cannot_happen_and_a_stuck_running_row_blocks(self, mini):
        """Data and the 'complete' status commit together. A 'running' row left by a crashed process (simulated
        here) means the latest run is not complete, so downstream stages refuse until a re-run."""
        from mel_agent.pipeline import IngestionIncomplete

        p, root, original = mini
        with p.store.write() as conn:
            p.store.record_ingest_run({"run_id": "ingest-crashed", "started_at": NOW, "source_root": str(root), "status": "running", "stats": {}}, conn)
        assert not p.store.ingestion_complete()
        with pytest.raises(IngestionIncomplete):
            p.decide_all(NOW)
        p.ingest(NOW)  # restart recovery: a fresh complete run supersedes the stuck one
        assert p.store.ingestion_complete() and p.store.latest_ingest_run()["run_id"] != "ingest-crashed"

    def test_repeated_ingestion_is_deterministic_with_fresh_run_ids(self, mini):
        p, root, original = mini
        a = p.store.latest_ingest_run()
        stats = p.ingest(NOW)
        b = p.store.latest_ingest_run()
        assert a["run_id"] != b["run_id"] and b["seq"] == a["seq"] + 1
        assert b["stats"]["content_fingerprint"] == a["stats"]["content_fingerprint"] and stats.insights_stored_valid == 1
        with p.store.read() as conn:
            assert conn.execute("SELECT COUNT(*) FROM insights").fetchone()[0] == 1
            assert conn.execute("SELECT COUNT(DISTINCT run_id) FROM insights").fetchone()[0] == 1

    def test_all_entry_points_see_one_consistent_snapshot_during_ingestion(self, mini, settings, registry):
        """While an import runs in another thread, readers see either the old complete snapshot or the new one."""
        from mel_agent.pipeline import Pipeline

        p, root, original = mini
        changed = self._changed(original)
        _mini_pack(root, settings, [changed])
        reader = Pipeline(p.settings, Store(p.store.path), registry)
        seen: set[str] = set()
        errors: list[str] = []
        stop = threading.Event()

        def read_loop():
            while not stop.is_set():
                row = reader.store.get_insight(original["insight_id"])
                raw = json.loads(row["raw_json"])
                if raw not in (original, changed):
                    errors.append("partial record")
                seen.add(raw["asset"]["name"])
                if not reader.store.ingestion_complete():
                    errors.append("incomplete seen")

        t = threading.Thread(target=read_loop)
        t.start()
        for _ in range(3):
            p.ingest(NOW)
            _mini_pack(root, settings, [original])
            p.ingest(NOW)
            _mini_pack(root, settings, [changed])
        stop.set(); t.join(timeout=30)
        assert errors == [] and seen

    def test_insight_rows_carry_the_active_run_id(self, pipeline):
        run = pipeline.store.latest_ingest_run()
        with pipeline.store.read() as conn:
            distinct = [r[0] for r in conn.execute("SELECT DISTINCT run_id FROM insights")]
        assert distinct == [run["run_id"]] and pipeline.store.active_ingest_run_id() == run["run_id"]


# =====================================================================================
# F3 (HIGH)  Answer choices could omit essential outcomes
# =====================================================================================

class TestF3AnswerCoverage:
    def _req(self, load_example, rules, calendar, **over):
        from mel_agent.generation.models import SurveyRequest
        from mel_agent.rules.eligibility import decide

        insight = dict(load_example("scenarios/1-mustard-aphid-spray/insight.json"), **over)
        d = decide(insight, rules, calendar)
        return SurveyRequest.build(survey_id_for(insight["insight_id"]), insight, None, "en-IN", d.send_window, rules.asks_for_resolution(insight["resolution_type"]))

    def _gen(self, settings, registry, items):
        from mel_agent.generation.generator import SurveyGenerator
        from mel_agent.generation.providers import ScriptedProvider

        return SurveyGenerator(settings.model_copy(update={"generation_fallback_to_template": False, "generation_max_attempts": 1}), registry,
                               ScriptedProvider([{"items": items, "rationale": "ok"}]), fallback=None)

    def test_codex_reproduction_input_available_cannot_lose_not_found(self, load_example, rules, calendar, settings, registry):
        """Reviewer: input_available narrowed to easy/hard left only affirmative answers and lost the
        could_not_get_input follow-up signal."""
        req = self._req(load_example, rules, calendar)
        result = self._gen(settings, registry, [{"intent": "input_available", "options": [{"value": "easy"}, {"value": "hard"}]}]).generate(req)
        assert not result.accepted and result.attempts[0]["problems"] == ["required_outcome_missing"]
        full = self._gen(settings, registry, [{"intent": "input_available"}]).generate(req)
        values = {o["value"]: o for o in full.survey["items"][0]["options"]}
        assert full.accepted and values["not_found"]["follow_up"] == "could_not_get_input"

    def test_codex_reproduction_crop_state_cannot_lose_worse(self, load_example, rules, calendar, settings, registry):
        req = self._req(load_example, rules, calendar)
        for subset in ([{"value": "better"}, {"value": "same"}], [{"value": "better"}], [{"value": "same"}, {"value": "better"}]):
            result = self._gen(settings, registry, [{"intent": "state_now", "options": subset}]).generate(req)
            assert not result.accepted and result.attempts[0]["problems"] == ["required_outcome_missing"], subset
        full = self._gen(settings, registry, [{"intent": "state_now", "options": [{"value": "worse"}, {"value": "better"}, {"value": "same"}]}]).generate(req)
        assert full.accepted and [o["value"] for o in full.survey["items"][0]["options"]] == ["better", "same", "worse"]  # catalogue order, not the model's

    def test_every_intent_rejects_every_single_omission(self, load_example, rules, calendar, settings, registry):
        from mel_agent.generation.catalog import QUESTION_CATALOG, allowed_intents, required_values
        from mel_agent.generation.models import SurveyRequest
        from mel_agent.rules.eligibility import decide

        base = load_example("scenarios/1-mustard-aphid-spray/insight.json")
        for intent, spec in QUESTION_CATALOG.items():
            if spec["type"] == "survey-scale":
                continue
            values = [v for v, _ in spec["options"]]
            assert required_values(intent) == set(values), intent  # fixed answer sets
            resolution = sorted(spec["resolutions"])[0]
            insight = dict(base, resolution_type=resolution)
            if resolution == "escalate_to_expert":
                insight["asset"] = {"name": "cow", "category": "livestock", "growth_stage": None}
            d = decide(insight, rules, calendar)
            req = SurveyRequest.build(survey_id_for(insight["insight_id"]), insight, None, "en-IN", d.send_window, rules.asks_for_resolution(resolution))
            allowed = allowed_intents(resolution, insight.get("concern"))
            assert intent in allowed, intent
            # An anchor question that names the asset keeps the relevance proxy satisfied, so acceptance below
            # depends only on answer coverage.
            anchor = next(a for a in allowed if a != intent and "{asset}" in QUESTION_CATALOG[a]["en"] and QUESTION_CATALOG[a]["type"] != "survey-scale")
            for drop in values:
                subset = [{"value": v} for v in values if v != drop]
                result = self._gen(settings, registry, [{"intent": anchor}, {"intent": intent, "options": subset}]).generate(req)
                assert not result.accepted and result.attempts[0]["problems"] == ["required_outcome_missing"], (intent, drop)
            result = self._gen(settings, registry, [{"intent": anchor}, {"intent": intent, "options": [{"value": v} for v in reversed(values)]}]).generate(req)
            assert result.accepted, (intent, result.attempts)
            assert [o["value"] for o in result.survey["items"][1]["options"]] == values, intent

    @pytest.mark.parametrize("options", [
        [{"value": "yes"}, {"value": "no"}, {"value": "yes"}],            # duplicate
        [{"value": "yes"}, {"value": "no"}, {"value": "better"}],         # foreign value
        [{"value": "yes", "label": "Spray petrol"}, {"value": "no"}],     # label is ignored (full set) -> accepted below
    ])
    def test_malformed_option_lists_are_malformed_not_silently_fixed(self, load_example, rules, calendar, settings, registry, options):
        req = self._req(load_example, rules, calendar)
        result = self._gen(settings, registry, [{"intent": "did_action", "options": options}]).generate(req)
        if len({o["value"] for o in options}) == 2 and all(o["value"] in ("yes", "no") for o in options) and len(options) == 2:
            assert result.accepted and [o["label"] for o in result.survey["items"][0]["options"]] == ["Yes", "No"]
        else:
            assert not result.accepted and result.attempts[0]["problems"] == ["malformed_provider_output"]

    ADVERSE = {"no", "not_yet", "not_found", "could_not", "not_available", "too_costly", "no_time", "unclear", "not_met", "same", "worse",
               "more", "spreading", "none", "need_help", "hard", "did_not_check", "partly"}

    def test_every_intent_can_distinguish_positive_from_negative_outcomes(self):
        """Every fixed answer set offers at least one adverse outcome and at least one non-adverse one, and every
        option the catalogue marks with a follow-up reason is adverse."""
        from mel_agent.generation.catalog import QUESTION_CATALOG

        for intent, spec in QUESTION_CATALOG.items():
            if spec["type"] == "survey-scale":
                assert spec["scale"][2] >= spec["scale"][0]  # a low score triggers follow-up
                continue
            values = [v for v, _ in spec["options"]]
            adverse = [v for v in values if v in self.ADVERSE]
            benign = [v for v in values if v not in self.ADVERSE]
            assert adverse and benign, (intent, values)
            assert all(v in self.ADVERSE for v, f in spec["options"] if f), intent

    def test_stored_handoff_missing_a_required_outcome_is_blocked_at_send(self, pipeline):
        insight = _eligible_insight(pipeline.store, preferred_channel="whatsapp")
        hid = pipeline.process_insight(insight["insight_id"], NOW)["generation"]["handoff_id"]
        row = pipeline.store.get_handoff(hid)
        hj = json.loads(row["handoff_json"])
        item = hj["survey"]["items"][1]  # state_now: better / same / worse
        item["options"] = [o for o in item["options"] if o["value"] != "worse"]
        with pipeline.store.write() as conn:
            conn.execute("UPDATE handoffs SET handoff_json = ? WHERE handoff_id = ?", (json.dumps(hj, ensure_ascii=False), hid))
        pipeline.clock.set(row["not_before"])
        rep = pipeline.broadcaster().tick()
        h = pipeline.store.get_handoff(hid)
        assert rep.sent == 0 and rep.blocked_unsafe == 1 and "required_outcome_missing" in h["state_detail"]

    def test_stored_handoff_with_a_stripped_follow_up_is_blocked_at_send(self, pipeline):
        insight = _eligible_insight(pipeline.store, preferred_channel="whatsapp")
        hid = pipeline.process_insight(insight["insight_id"], NOW)["generation"]["handoff_id"]
        row = pipeline.store.get_handoff(hid)
        hj = json.loads(row["handoff_json"])
        for o in hj["survey"]["items"][1]["options"]:
            o.pop("follow_up", None)
        with pipeline.store.write() as conn:
            conn.execute("UPDATE handoffs SET handoff_json = ? WHERE handoff_id = ?", (json.dumps(hj, ensure_ascii=False), hid))
        pipeline.clock.set(row["not_before"])
        rep = pipeline.broadcaster().tick()
        assert rep.blocked_unsafe == 1 and "follow_up_signal_missing" in pipeline.store.get_handoff(hid)["state_detail"]

    def test_validate_survey_text_reports_coverage_for_shared_wording(self, pipeline):
        """'How is your {asset} now?' is rendered by two intents with different answer sets; either full set passes."""
        from mel_agent.generation.catalog import option
        from mel_agent.generation.safety import validate_survey_text

        insight = _eligible_insight(pipeline.store)
        hid = pipeline.process_insight(insight["insight_id"], NOW)["generation"]["handoff_id"]
        survey = json.loads(pipeline.store.get_handoff(hid)["handoff_json"])["survey"]
        lang = survey["language"]
        item = next(i for i in survey["items"] if i["prompt"].startswith(("How is your", "अब आपकी")))
        item["options"] = [option("better", lang), option("same", lang), option("worse", lang, "crop_or_animal_damaged"), option("not_met", lang)]
        assert validate_survey_text(survey, lang) == []
        item["options"] = [option("better", lang), option("same", lang)]
        assert "required_outcome_missing" in validate_survey_text(survey, lang)

    def test_system_prompt_no_longer_offers_narrowing(self):
        from mel_agent.generation.providers import SYSTEM_PROMPT

        assert "narrow" not in SYSTEM_PROMPT.lower() and "fixed per intent" in SYSTEM_PROMPT


# =====================================================================================
# F4 (MEDIUM)  Client construction before authorisation
# =====================================================================================

class TestF4ClientConstructionOrder:
    @pytest.fixture
    def guarded(self, monkeypatch):
        """A client factory that records every construction and can be armed to raise."""
        import mel_agent.llm.bedrock as bedrock

        calls: list[str] = []
        state = {"armed": True}

        def factory(settings, service="bedrock-runtime", total_max_attempts=None):
            if state["armed"]:
                raise AssertionError("boto3 client constructed before authorisation, pricing and headroom were established")
            calls.append(f"{service}:{total_max_attempts}")
            c = _client(total_max_attempts)
            c.converse = lambda **_k: _response(inp=10, out=5)
            return c

        monkeypatch.setattr(bedrock, "make_client", factory)
        return calls, state

    def _wrapped(self, tmp_path, settings):
        from mel_agent.llm.bedrock import BedrockInvoker
        from mel_agent.llm.budgeted import BudgetedInvoker

        ctl = BudgetController(Store(tmp_path / "b.db"), settings, PRICING)
        return BudgetedInvoker(BedrockInvoker(settings, pricing=PRICING), ctl), ctl

    def test_codex_reproduction_disabled_inference_never_builds_a_client(self, tmp_path, guarded):
        inv, ctl = self._wrapped(tmp_path, _settings(allow_paid_inference=False))
        with pytest.raises(PaidInferenceDisabled):
            inv.converse("hi", max_tokens=10)
        assert guarded[0] == [] and inv.invoker._client is None and ctl.ledger() == []

    def test_unpriced_model_and_no_headroom_never_build_a_client(self, tmp_path, guarded):
        inv, ctl = self._wrapped(tmp_path, _settings())
        with pytest.raises(BudgetUnavailable):
            inv.converse("hi", model_id="unpriced-model", max_tokens=10)
        r = ctl.reserve(MODEL, 225_000_000, 0); ctl.settle(r, TokenUsage(input_tokens=225_000_000))
        with pytest.raises(BudgetExceeded):
            inv.converse("hi", max_tokens=10)
        assert guarded[0] == [] and inv.invoker._client is None

    def test_unresolved_cap_and_lost_ownership_never_build_a_client(self, tmp_path, guarded):
        from mel_agent.llm.budgeted import OwnershipLost

        inv, ctl = self._wrapped(tmp_path, _settings(budget_max_unresolved=1))
        with pytest.raises(OwnershipLost):
            inv.converse("hi", max_tokens=10, may_continue=lambda: False)
        ctl.mark_unresolved(ctl.reserve(MODEL, 10, 10), "x")
        with pytest.raises(BudgetUnavailable):
            inv.converse("hi", max_tokens=10)
        assert guarded[0] == [] and inv.invoker._client is None

    def test_client_is_built_only_after_the_reservation_exists(self, tmp_path, guarded):
        calls, state = guarded
        inv, ctl = self._wrapped(tmp_path, _settings())
        import mel_agent.llm.bedrock as bedrock

        original = bedrock.make_client
        order: list[str] = []

        def recording(settings, service="bedrock-runtime", total_max_attempts=None):
            order.append(f"construct:open_reservations={len([r for r in ctl.ledger() if r['kind'] == 'reserve'])}")
            return original(settings, service, total_max_attempts)

        state["armed"] = False
        bedrock.make_client = recording
        try:
            result = inv.converse("hi", max_tokens=10)
        finally:
            bedrock.make_client = original
        assert order == ["construct:open_reservations=1"] and calls == ["bedrock-runtime:1"] and result.usage_verified
        assert _kinds(ctl) == ["reserve", "settle"]

    def test_smoke_cli_rejections_perform_no_client_construction(self, load_script, monkeypatch, clean_mel_env, no_aws, settings, tmp_path, capsys):
        import mel_agent.llm.bedrock as bedrock

        module = load_script("bedrock_smoke")
        monkeypatch.setattr(bedrock, "make_client", lambda *a, **k: (_ for _ in ()).throw(AssertionError("client constructed")))
        monkeypatch.setattr(module, "credentials_available", lambda *a, **k: (_ for _ in ()).throw(AssertionError("credentials looked up")))
        monkeypatch.setenv("MEL_BEDROCK_REGION", "us-west-2")
        monkeypatch.setenv("MEL_DATABASE_URL", f"sqlite:///{tmp_path / 'l.db'}")
        monkeypatch.setenv("MEL_PRICING_FILE", str(settings.pricing_file))
        monkeypatch.setenv("MEL_ALLOW_PAID_INFERENCE", "false")
        assert module.main(["--yes"]) == 2
        monkeypatch.setenv("MEL_ALLOW_PAID_INFERENCE", "true")
        assert module.main(["--yes", "--model", "no-such-model"]) == 2


# =====================================================================================
# F5 (MEDIUM)  A superseded worker could start a paid retry
# =====================================================================================

class TestF5NoRetryAfterSupersession:
    def _worker_b(self, pipeline, settings, registry):
        from mel_agent.delivery.clock import SimulatedClock
        from mel_agent.pipeline import Pipeline

        return Pipeline(settings, Store(pipeline.store.path), registry, clock=SimulatedClock(NOW))

    def test_codex_reproduction_timed_out_worker_does_not_retry_after_losing_the_claim(self, pipeline, settings, registry, tmp_path):
        """Reviewer: A's request timed out after its lease expired and B had scheduled the survey; A then started
        another paid attempt. Now the ownership check runs before every new request, including retries."""
        from mel_agent.generation.generator import SurveyGenerator
        from mel_agent.generation.providers import BedrockProvider
        from mel_agent.llm.bedrock import BedrockInvoker
        from mel_agent.llm.budgeted import BudgetedInvoker

        insight = _eligible_insight(pipeline.store, preferred_channel="whatsapp")
        sid = survey_id_for(insight["insight_id"])
        worker_b = self._worker_b(pipeline, settings, registry)
        paid = _settings(bedrock_paid_retry_after_timeout=True, bedrock_paid_app_attempts=3, budget_max_unresolved=5)
        ctl = BudgetController(Store(tmp_path / "b.db"), paid, PRICING)
        client = _client()
        calls = {"n": 0}

        def converse(**_k):
            calls["n"] += 1
            # A is slow: its lease lapses and B takes over and schedules while A's request is in flight...
            with pipeline.store.write() as conn:
                conn.execute("UPDATE generation_claims SET lease_until = ? WHERE insight_id = ?", (time.time() - 1, insight["insight_id"]))
            assert worker_b.process_insight(insight["insight_id"], NOW)["generation"]["status"] == "scheduled"
            raise ReadTimeoutError(endpoint_url="https://bedrock")  # ...then the in-flight request times out

        client.converse = converse
        invoker = BudgetedInvoker(BedrockInvoker(paid, pricing=PRICING, client=client), ctl)
        pipeline.generator = SurveyGenerator(settings.model_copy(update={"generation_max_attempts": 3}), registry, BedrockProvider(invoker), fallback=None)
        out = pipeline.process_insight(insight["insight_id"], NOW)["generation"]
        assert out["status"] == "lost_claim" and calls["n"] == 1
        # The one request that was in flight is accounted for (unresolved); no second reservation exists.
        assert _kinds(ctl) == ["reserve", "unresolved"]
        with pipeline.store.read() as conn:
            assert conn.execute("SELECT COUNT(*) FROM handoffs WHERE survey_id = ?", (sid,)).fetchone()[0] == 1
        assert pipeline.store.get_claim(insight["insight_id"])["status"] == "done"

    def test_generator_level_retry_is_refused_once_ownership_is_gone(self, load_example, rules, calendar, settings, registry):
        from mel_agent.generation.generator import SurveyGenerator
        from mel_agent.generation.models import SurveyRequest
        from mel_agent.generation.providers import ScriptedProvider
        from mel_agent.rules.eligibility import decide
        import dataclasses

        insight = load_example("scenarios/1-mustard-aphid-spray/insight.json")
        d = decide(insight, rules, calendar)
        req = SurveyRequest.build(survey_id_for(insight["insight_id"]), insight, None, "en-IN", d.send_window, "x")
        owner = {"ok": True}
        scripted = ScriptedProvider([{"items": [{"intent": "reached_expert"}]}, {"items": [{"intent": "did_action"}]}])  # first invalid -> retry wanted

        def may_continue():
            ok = owner["ok"]
            owner["ok"] = False  # ownership lapses right after the first check
            return ok

        req = dataclasses.replace(req, may_continue=may_continue)
        gen = SurveyGenerator(settings.model_copy(update={"generation_max_attempts": 3}), registry, scripted)  # template fallback configured
        result = gen.generate(req)
        assert scripted.calls == 1 and result.aborted and not result.accepted
        assert result.attempts[-1]["error"] == "ownership_lost" and all(a["provider"] != "template" for a in result.attempts)  # no fallback either

    def test_budgeted_retry_after_timeout_checks_ownership_before_each_attempt(self, tmp_path):
        from mel_agent.llm.budgeted import OwnershipLost

        client = _client()
        n = {"calls": 0}

        def timeout(**_k):
            n["calls"] += 1
            raise ReadTimeoutError(endpoint_url="https://bedrock")

        client.converse = timeout
        inv, ctl = _invoker(tmp_path, client, app_attempts=3, retry_after_timeout=True, budget_max_unresolved=5)
        checks = iter([True, True, False])  # attempt 1: start + pre-send ok (sent, times out); attempt 2: start check lost
        with pytest.raises(OwnershipLost):
            inv.converse("hi", max_tokens=10, may_continue=lambda: next(checks))
        assert n["calls"] == 1 and _kinds(ctl) == ["reserve", "unresolved"]

    def test_in_flight_completion_after_expiry_is_still_settled(self, pipeline, settings, registry, tmp_path):
        """A request already sent before the lease lapsed completes and is settled normally; only NEW requests
        are refused. Persistence is fenced separately."""
        from mel_agent.generation.generator import SurveyGenerator
        from mel_agent.generation.providers import BedrockProvider
        from mel_agent.llm.bedrock import BedrockInvoker
        from mel_agent.llm.budgeted import BudgetedInvoker

        insight = _eligible_insight(pipeline.store)
        worker_b = self._worker_b(pipeline, settings, registry)
        ctl = BudgetController(Store(tmp_path / "b.db"), _settings(), PRICING)
        client = _client()

        def converse(**_k):
            with pipeline.store.write() as conn:
                conn.execute("UPDATE generation_claims SET lease_until = ? WHERE insight_id = ?", (time.time() - 1, insight["insight_id"]))
            worker_b.process_insight(insight["insight_id"], NOW)
            text = json.dumps({"items": [{"intent": "did_action"}], "rationale": "ok"})
            r = _response(inp=50, out=20)
            r["output"]["message"]["content"][0]["text"] = text
            return r

        client.converse = converse
        pipeline.generator = SurveyGenerator(settings, registry, BedrockProvider(BudgetedInvoker(BedrockInvoker(_settings(), pricing=PRICING, client=client), ctl)), fallback=None)
        out = pipeline.process_insight(insight["insight_id"], NOW)["generation"]
        assert out["status"] == "lost_claim" and _kinds(ctl) == ["reserve", "settle"]
        with pipeline.store.read() as conn:
            assert conn.execute("SELECT COUNT(*) FROM handoffs WHERE survey_id = ?", (survey_id_for(insight["insight_id"]),)).fetchone()[0] == 1

    def test_restart_takes_over_an_expired_claim_exactly_once(self, pipeline, settings, registry):
        insight = _eligible_insight(pipeline.store)
        sid = survey_id_for(insight["insight_id"])
        with pipeline.store.write() as conn:
            pipeline.store.claim_generation(conn, insight["insight_id"], sid, "dead-process", NOW, lease_seconds=5, wall=time.time() - 100)
        restarted = self._worker_b(pipeline, settings, registry)
        assert restarted.process_insight(insight["insight_id"], NOW)["generation"]["status"] == "scheduled"
        assert pipeline.process_insight(insight["insight_id"], NOW)["generation"]["status"] == "already_scheduled"


# =====================================================================================
# F6 (MEDIUM)  Older database schemas failed during generation
# =====================================================================================

_LEGACY_CLAIMS = ("CREATE TABLE generation_claims_legacy (insight_id TEXT PRIMARY KEY, survey_id TEXT NOT NULL UNIQUE, status TEXT NOT NULL, "
                  "owner TEXT NOT NULL, claimed_at TEXT NOT NULL, updated_at TEXT NOT NULL)")
_LEGACY_RUNS = ("CREATE TABLE ingest_runs_legacy (run_id TEXT PRIMARY KEY, started_at TEXT NOT NULL, finished_at TEXT, source_root TEXT NOT NULL, "
                "status TEXT NOT NULL DEFAULT 'running', error TEXT, stats_json TEXT NOT NULL)")
_INSIGHT_COLS = ("insight_id, farmer_id, created_at, conversation_language, resolution_type, asset_name, concern, severity, quality_flag, "
                 "schema_valid, quarantine_reason, source_file, line_no, content_hash, raw_json, ingested_at")
_LEGACY_INSIGHTS = (f"CREATE TABLE insights_legacy (insight_id TEXT PRIMARY KEY, farmer_id TEXT, created_at TEXT, conversation_language TEXT, "
                    "resolution_type TEXT, asset_name TEXT, concern TEXT, severity TEXT, quality_flag TEXT, schema_valid INTEGER NOT NULL, "
                    "quarantine_reason TEXT, source_file TEXT NOT NULL, line_no INTEGER NOT NULL, content_hash TEXT NOT NULL, raw_json TEXT NOT NULL, "
                    "ingested_at TEXT NOT NULL)")


def _downgrade_to_8bb4569(path: str, *, generating_claim: tuple[str, str] | None = None) -> None:
    """Rewrite an ingested database into the 8bb4569 layout (no token/lease, no run seq, no ledger uniqueness)."""
    con = sqlite3.connect(path)
    con.executescript(f"""
        BEGIN;
        {_LEGACY_CLAIMS};
        INSERT INTO generation_claims_legacy SELECT insight_id, survey_id, status, owner, claimed_at, updated_at FROM generation_claims;
        DROP TABLE generation_claims; ALTER TABLE generation_claims_legacy RENAME TO generation_claims;
        {_LEGACY_RUNS};
        INSERT INTO ingest_runs_legacy SELECT run_id, started_at, finished_at, source_root, status, error, stats_json FROM ingest_runs;
        DROP TABLE ingest_runs; ALTER TABLE ingest_runs_legacy RENAME TO ingest_runs;
        {_LEGACY_INSIGHTS};
        INSERT INTO insights_legacy SELECT {_INSIGHT_COLS} FROM insights;
        DROP TABLE insights; ALTER TABLE insights_legacy RENAME TO insights;
        CREATE INDEX ix_insights_farmer ON insights (farmer_id, created_at);
        CREATE INDEX ix_insights_created ON insights (created_at, insight_id);
        DROP INDEX IF EXISTS ux_ledger_reservation_kind;
        DROP INDEX IF EXISTS ux_ledger_terminal;
        DELETE FROM kv WHERE k = 'schema_version';
        COMMIT;
    """)
    if generating_claim is not None:
        con.execute("INSERT INTO generation_claims (insight_id, survey_id, status, owner, claimed_at, updated_at) VALUES (?, ?, 'generating', 'old-worker', ?, ?)",
                    (generating_claim[0], generating_claim[1], NOW, NOW))
        con.commit()
    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    con.close()


class TestF6SchemaMigration:
    @pytest.fixture
    def legacy_db(self, pipeline, tmp_path):
        """A fully ingested database with one scheduled survey, downgraded to the 8bb4569 layout."""
        insight = _eligible_insight(pipeline.store)
        pipeline.process_insight(insight["insight_id"], NOW)
        other = next(json.loads(r["raw_json"]) for r in pipeline.store.iter_insights(only_valid=True)
                     if json.loads(r["raw_json"]).get("resolution_type") == "direct_action" and (json.loads(r["raw_json"]).get("verification") or {}).get("needed")
                     and json.loads(r["raw_json"]).get("severity") != "critical" and r["insight_id"] != insight["insight_id"])
        pipeline.store.checkpoint()
        path = tmp_path / "legacy.db"
        shutil.copy(pipeline.store.path, path)
        _downgrade_to_8bb4569(str(path), generating_claim=(other["insight_id"], survey_id_for(other["insight_id"])))
        return path, insight, other

    def test_codex_reproduction_legacy_database_is_upgraded_and_generation_works(self, legacy_db, settings, registry):
        """Reviewer: on a database from 8bb4569 generation failed with 'no such column: token'."""
        from mel_agent.delivery.clock import SimulatedClock
        from mel_agent.pipeline import Pipeline

        path, done_insight, pending_insight = legacy_db
        raw = sqlite3.connect(str(path))
        with pytest.raises(sqlite3.OperationalError, match="no such column: token"):
            raw.execute("SELECT token FROM generation_claims").fetchall()  # the defect, before the upgrade
        counts_before = {t: raw.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("insights", "farmers", "handoffs", "surveys", "generation_claims", "ingest_runs")}
        raw.close()
        store = Store(path)  # upgrade happens here
        assert store.schema_version() == 3
        with store.read() as conn:
            counts_after = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in counts_before}
            cols = {r[1] for r in conn.execute("PRAGMA table_info(generation_claims)")}
            run_cols = {r[1] for r in conn.execute("PRAGMA table_info(ingest_runs)")}
        assert counts_after == counts_before and {"token", "lease_until"} <= cols and {"seq", "recorded_at"} <= run_cols
        assert store.ingestion_complete()  # the legacy complete run (no seq) is still the active dataset
        p = Pipeline(settings, store, registry, clock=SimulatedClock(NOW))
        assert p.process_insight(done_insight["insight_id"], NOW)["generation"]["status"] == "already_scheduled"
        # The legacy in-progress claim has an expired (zero) lease: it is taken over, not stuck forever.
        out = p.process_insight(pending_insight["insight_id"], NOW)["generation"]
        assert out["status"] == "scheduled" and store.get_claim(pending_insight["insight_id"])["status"] == "done"

    def test_repeated_startup_is_idempotent(self, legacy_db):
        path, _, _ = legacy_db
        a = Store(path)
        with a.read() as conn:
            schema_a = sorted(r[0] for r in conn.execute("SELECT sql FROM sqlite_master WHERE sql IS NOT NULL"))
            rows_a = conn.execute("SELECT COUNT(*) FROM insights").fetchone()[0]
        for _ in range(3):
            b = Store(path)
            with b.read() as conn:
                assert sorted(r[0] for r in conn.execute("SELECT sql FROM sqlite_master WHERE sql IS NOT NULL")) == schema_a
                assert conn.execute("SELECT COUNT(*) FROM insights").fetchone()[0] == rows_a
            assert b.schema_version() == 3

    def test_fresh_database_has_the_current_version(self, tmp_path):
        s = Store(tmp_path / "fresh.db")
        assert s.schema_version() == 3
        with s.read() as conn:
            assert {"token", "lease_until"} <= {r[1] for r in conn.execute("PRAGMA table_info(generation_claims)")}
            assert {"seq", "recorded_at"} <= {r[1] for r in conn.execute("PRAGMA table_info(ingest_runs)")}
            assert "run_id" in {r[1] for r in conn.execute("PRAGMA table_info(insights)")}

    def test_interrupted_upgrade_leaves_the_old_version_intact_and_completes_next_time(self, legacy_db):
        path, _, _ = legacy_db

        class Crashing(Store):
            def _initialise(self):
                with self.write() as conn:
                    conn.execute("ALTER TABLE generation_claims ADD COLUMN token TEXT NOT NULL DEFAULT ''")
                    raise RuntimeError("power loss")  # inside the transaction: rolled back

        with pytest.raises(RuntimeError):
            Crashing(path)
        raw = sqlite3.connect(str(path))
        assert "token" not in {r[1] for r in raw.execute("PRAGMA table_info(generation_claims)")}
        assert raw.execute("SELECT v FROM kv WHERE k = 'schema_version'").fetchone() is None
        raw.close()
        s = Store(path)
        assert s.schema_version() == 3
        with s.read() as conn:
            assert "token" in {r[1] for r in conn.execute("PRAGMA table_info(generation_claims)")}

    def test_concurrent_startup_on_a_legacy_database(self, legacy_db):
        path, _, _ = legacy_db
        barrier = threading.Barrier(6)
        errors: list[BaseException] = []
        versions: list[int] = []

        def start():
            try:
                barrier.wait(timeout=10)
                versions.append(Store(path).schema_version())
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=start) for _ in range(6)]
        [t.start() for t in threads]; [t.join(timeout=60) for t in threads]
        assert errors == [] and versions == [3] * 6

    def test_duplicate_ledger_rows_refuse_the_upgrade_with_a_clear_error(self, legacy_db):
        from mel_agent.store import StoreError

        path, _, _ = legacy_db
        raw = sqlite3.connect(str(path))
        for entry in ("a", "b"):
            raw.execute("INSERT INTO budget_ledger (entry_id, reservation_id, created_at, kind, model_id, estimated_usd, actual_usd) "
                        "VALUES (?, 'r1', '2026-11-01T00:00:00', 'settle', 'm', 1.0, 0.5)", (entry,))
        raw.commit(); raw.close()
        with pytest.raises(StoreError, match="duplicate reservation events"):
            Store(path)
        raw = sqlite3.connect(str(path))
        assert "token" not in {r[1] for r in raw.execute("PRAGMA table_info(generation_claims)")}  # nothing was changed
        raw.close()

    def test_api_startup_fails_clearly_on_an_unupgradable_database(self, legacy_db, settings):
        from mel_agent.main import create_app
        from mel_agent.store import StoreError

        path, _, _ = legacy_db
        raw = sqlite3.connect(str(path))
        for entry in ("a", "b"):
            raw.execute("INSERT INTO budget_ledger (entry_id, reservation_id, created_at, kind, model_id, estimated_usd) VALUES (?, 'r1', 'z', 'reserve', 'm', 1.0)", (entry,))
        raw.commit(); raw.close()
        from fastapi.testclient import TestClient
        from pydantic import SecretStr

        app = create_app(settings.model_copy(update={"database_url": f"sqlite:///{path}", "operator_token": SecretStr("operator-token-for-tests-123")}))
        with pytest.raises(StoreError):
            with TestClient(app):
                pass
