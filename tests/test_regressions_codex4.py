"""Regression tests for the FOURTH independent (Codex) review of commit 9c791691.

One class per finding, in the review's order. Each class starts with the reviewer's
reproduction (``test_codex_reproduction_*``) and continues with adversarial variants.
Every reproduction fails on the 9c791691 baseline.

Nothing here reaches AWS: boto3 clients are built with fake credentials, their
``converse`` method is replaced, and the autouse ``no_network`` guard applies.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import threading
import time

import boto3
import pytest
from botocore.config import Config
from botocore.exceptions import ClientError

from mel_agent.budget import BudgetController, BudgetUnavailable
from mel_agent.config import Settings
from mel_agent.llm.pricing import ModelPrice, PricingTable
from mel_agent.rules.scheduling import survey_id_for
from mel_agent.store import Store, StoreError

NOW = "2026-11-01T00:00:00+05:30"
MODEL = "m-test"
PRICING = PricingTable({MODEL: ModelPrice(input=1.0, output=2.0)})


def _settings(**over) -> Settings:
    base = {"allow_paid_inference": True, "budget_safety_factor": 1.0, "bedrock_model_id": MODEL, "bedrock_region": "us-west-2", "_env_file": None}
    base.update(over)
    return Settings(**base)


def _client(total_max_attempts: int | None = 1):
    cfg = Config(retries={"total_max_attempts": total_max_attempts}) if total_max_attempts is not None else None
    return boto3.client("bedrock-runtime", region_name="us-west-2", aws_access_key_id="testing", aws_secret_access_key="testing", config=cfg)


_MISSING = object()


def _response(inp=1000, out=500, metadata=_MISSING, text="ok"):
    """A Converse response. ``metadata`` replaces the whole ResponseMetadata block (``_MISSING`` = verified zero)."""
    r = {"output": {"message": {"role": "assistant", "content": [{"text": text}]}}, "stopReason": "end_turn", "metrics": {"latencyMs": 5},
         "usage": {"inputTokens": inp, "outputTokens": out, "totalTokens": inp + out}}
    if metadata is _MISSING:
        r["ResponseMetadata"] = {"RetryAttempts": 0, "HTTPStatusCode": 200}
    elif not (isinstance(metadata, str) and metadata == "ABSENT"):
        r["ResponseMetadata"] = metadata
    return r


def _error(code: str, metadata=_MISSING) -> ClientError:
    """A ClientError whose payload carries the given ResponseMetadata (set after construction, because botocore's
    own constructor assumes a dict there; the accounting boundary must not share that assumption)."""
    exc = ClientError({"Error": {"Code": code, "Message": "x"}, "ResponseMetadata": {"RetryAttempts": 0, "HTTPStatusCode": 400}}, "Converse")
    if metadata is _MISSING:
        return exc
    if isinstance(metadata, str) and metadata == "ABSENT":
        del exc.response["ResponseMetadata"]
    else:
        exc.response["ResponseMetadata"] = metadata
    return exc


def _kinds(ctl: BudgetController) -> list[str]:
    return [row["kind"] for row in sorted(ctl.ledger(), key=lambda r: (r["created_at"], r["entry_id"]))]


def _invoker(tmp_path, client, **over):
    from mel_agent.llm.bedrock import BedrockInvoker
    from mel_agent.llm.budgeted import BudgetedInvoker

    settings = _settings(**{k: v for k, v in over.items() if k.startswith(("bedrock", "budget"))})
    ctl = BudgetController(Store(tmp_path / "b.db"), settings, PRICING)
    inv = BudgetedInvoker(BedrockInvoker(settings, pricing=PRICING, client=client), ctl,
                          **{k: v for k, v in over.items() if k in ("app_attempts", "retry_after_timeout")})
    return inv, ctl


def _eligible_insight(store: Store, **props):
    for row in store.iter_insights(only_valid=True):
        obj = json.loads(row["raw_json"])
        if (obj.get("verification") or {}).get("needed") and obj.get("severity") not in ("critical",) and obj.get("resolution_type") == "direct_action" \
                and all(obj.get(k) == v for k, v in props.items()):
            return obj
    raise AssertionError("no eligible insight")


MALFORMED_METADATA = [
    pytest.param("ABSENT", id="no-ResponseMetadata"),
    pytest.param(None, id="ResponseMetadata=None"),
    pytest.param([], id="ResponseMetadata=[]"),
    pytest.param("meta", id="ResponseMetadata=str"),
    pytest.param({}, id="RetryAttempts-missing"),
    pytest.param({"HTTPStatusCode": 200}, id="only-status"),
    pytest.param({"RetryAttempts": "0"}, id="str-0"),
    pytest.param({"RetryAttempts": "2"}, id="str-2"),
    pytest.param({"RetryAttempts": True}, id="bool-True"),
    pytest.param({"RetryAttempts": False}, id="bool-False"),
    pytest.param({"RetryAttempts": -1}, id="negative"),
    pytest.param({"RetryAttempts": 0.0}, id="float-0.0"),
    pytest.param({"RetryAttempts": None}, id="None"),
    pytest.param({"RetryAttempts": {"n": 0}}, id="nested-dict"),
    pytest.param({"RetryAttempts": [0]}, id="list"),
]


# =====================================================================================
# F1 (MEDIUM)  Malformed retry metadata restored headroom
# =====================================================================================

class TestF1RetryMetadataStates:
    def test_codex_reproduction_three_malformed_throttles_do_not_leave_committed_at_zero(self, tmp_path):
        """Reviewer: ResponseMetadata=None / [] / missing RetryAttempts were read as zero retries, so three mocked
        throttles produced reserve -> release three times and committed spend stayed $0."""
        client = _client()
        envelopes = iter([None, [], {}])
        client.converse = lambda **_k: (_ for _ in ()).throw(_error("ThrottlingException", next(envelopes)))
        inv, ctl = _invoker(tmp_path, client, app_attempts=3, budget_max_unresolved=10)
        for _ in range(3):
            with pytest.raises(ClientError):
                inv.converse("hi", max_tokens=1000)
        s = ctl.status()
        assert _kinds(ctl) == ["reserve", "unresolved"] * 3 and "release" not in _kinds(ctl)
        assert s.unresolved_count == 3 and s.committed_usd == pytest.approx(3 * float(ctl.estimate_cost(MODEL, ctl.estimate_tokens("hi"), 1000)))

    def test_codex_reproduction_malformed_metadata_on_success_is_not_settled(self, tmp_path):
        client = _client()
        for n, bad in enumerate((None, [], {})):
            client.converse = (lambda b: (lambda **_k: _response(inp=10, out=1, metadata=b)))(bad)
            inv, ctl = _invoker(tmp_path / f"case{n}", client)
            result = inv.converse("hi", max_tokens=100_000)
            s = ctl.status()
            assert s.calls_settled == 0 and s.unresolved_count == 1, bad
            assert result.estimated_cost_usd == pytest.approx(s.committed_usd, abs=1e-6) and s.committed_usd >= 0.2  # the full estimate stays

    @pytest.mark.parametrize("metadata", MALFORMED_METADATA)
    def test_every_malformed_envelope_on_an_error_is_unresolved_and_stops(self, tmp_path, metadata):
        client = _client()
        n = {"calls": 0}

        def fail(**_k):
            n["calls"] += 1
            raise _error("ThrottlingException", metadata)

        client.converse = fail
        inv, ctl = _invoker(tmp_path, client, app_attempts=3)
        with pytest.raises(ClientError):
            inv.converse("hi", max_tokens=100)
        assert n["calls"] == 1 and _kinds(ctl) == ["reserve", "unresolved"]

    @pytest.mark.parametrize("metadata", MALFORMED_METADATA)
    def test_every_malformed_envelope_on_a_success_is_unresolved(self, tmp_path, metadata):
        client = _client()
        client.converse = lambda **_k: _response(metadata=metadata)
        inv, ctl = _invoker(tmp_path, client)
        inv.converse("hi", max_tokens=100)
        assert _kinds(ctl) == ["reserve", "unresolved"]

    def test_verified_states_still_behave(self, tmp_path):
        client = _client()
        client.converse = lambda **_k: _response(metadata={"RetryAttempts": 0})
        inv, ctl = _invoker(tmp_path, client)
        inv.converse("hi", max_tokens=100)
        assert _kinds(ctl) == ["reserve", "settle"]
        client.converse = lambda **_k: _response(metadata={"RetryAttempts": 1})
        inv.converse("hi", max_tokens=100)
        assert _kinds(ctl) == ["reserve", "settle", "reserve", "unresolved"]
        client.converse = lambda **_k: (_ for _ in ()).throw(_error("ThrottlingException", {"RetryAttempts": 0}))
        from mel_agent.llm.budgeted import PaidCallFailed

        with pytest.raises(PaidCallFailed):
            inv.converse("hi", max_tokens=100)
        assert _kinds(ctl)[-4:] == ["reserve", "release", "reserve", "release"]

    def test_repeated_malformed_responses_cannot_restore_headroom_and_hit_the_cap(self, tmp_path):
        client = _client()
        client.converse = lambda **_k: _response(metadata=None)
        inv, ctl = _invoker(tmp_path, client, budget_max_unresolved=3)
        for _ in range(3):
            inv.converse("hi", max_tokens=1000)
        with pytest.raises(BudgetUnavailable, match="unresolved"):
            inv.converse("hi", max_tokens=1000)
        assert ctl.status().unresolved_count == 3 and ctl.status().committed_usd > 0

    def test_parser_three_states(self):
        from mel_agent.llm.bedrock import retry_attempts_in

        assert retry_attempts_in({"ResponseMetadata": {"RetryAttempts": 0}}) == 0
        assert retry_attempts_in({"ResponseMetadata": {"RetryAttempts": 3}}) == 3
        for bad in ({}, None, [], "x", 7, {"ResponseMetadata": None}, {"ResponseMetadata": []}, {"ResponseMetadata": {}},
                    {"ResponseMetadata": {"RetryAttempts": "0"}}, {"ResponseMetadata": {"RetryAttempts": True}},
                    {"ResponseMetadata": {"RetryAttempts": -1}}, {"ResponseMetadata": {"RetryAttempts": 0.0}}, {"ResponseMetadata": {"RetryAttempts": [0]}}):
            assert retry_attempts_in(bad) is None, bad

    def test_inference_result_defaults_to_unknown(self):
        from mel_agent.llm.bedrock import InferenceResult

        r = InferenceResult(MODEL, "ok", "end_turn", None, 1.0, 1, None)
        assert r.retry_attempts is None

    def test_raw_invoker_reports_unknown_for_a_stub_without_metadata(self):
        from botocore.stub import Stubber

        from mel_agent.llm.bedrock import BedrockInvoker

        client = _client()
        inv = BedrockInvoker(_settings(), pricing=PRICING, client=client)
        base = {"output": {"message": {"role": "assistant", "content": [{"text": "ok"}]}}, "stopReason": "end_turn",
                "usage": {"inputTokens": 1, "outputTokens": 1, "totalTokens": 2}, "metrics": {"latencyMs": 5}}
        with Stubber(client) as stub:
            stub.add_response("converse", base)
            assert inv.converse("hi", max_tokens=16).retry_attempts is None
            stub.add_response("converse", {**base, "ResponseMetadata": {"RetryAttempts": 0, "HTTPStatusCode": 200}})
            assert inv.converse("hi", max_tokens=16).retry_attempts == 0


# =====================================================================================
# F2 (MEDIUM)  Scale questions bypassed intent validation
# =====================================================================================

class TestF2ScaleValidation:
    @pytest.fixture
    def scale_handoff(self, pipeline, settings, registry):
        """A scheduled hand-off whose second item is the advice_useful scale question."""
        from mel_agent.generation.generator import SurveyGenerator
        from mel_agent.generation.providers import ScriptedProvider

        insight = _eligible_insight(pipeline.store, preferred_channel="whatsapp")
        pipeline.generator = SurveyGenerator(settings.model_copy(update={"generation_fallback_to_template": False}), registry,
                                             ScriptedProvider([{"items": [{"intent": "did_action"}, {"intent": "advice_useful"}], "rationale": "ok"}]), fallback=None)
        out = pipeline.process_insight(insight["insight_id"], NOW)["generation"]
        assert out["status"] == "scheduled"
        row = pipeline.store.get_handoff(out["handoff_id"])
        hj = json.loads(row["handoff_json"])
        assert hj["survey"]["items"][1]["type"] == "survey-scale"
        return pipeline, row, hj

    def _send_mutated(self, pipeline, row, hj, mutate):
        mutate(hj["survey"]["items"][1])
        with pipeline.store.write() as conn:
            conn.execute("UPDATE handoffs SET handoff_json = ? WHERE handoff_id = ?", (json.dumps(hj, ensure_ascii=False), row["handoff_id"]))
        pipeline.clock.set(row["not_before"])
        rep = pipeline.broadcaster().tick()
        return rep, pipeline.store.get_handoff(row["handoff_id"])

    def test_codex_reproduction_removed_follow_up_is_blocked_at_send(self, scale_handoff):
        """Reviewer: deleting follow_up_at_or_below / follow_up_reason left a schema-valid document that was sent."""
        pipeline, row, hj = scale_handoff
        survey = json.loads(json.dumps(hj["survey"]))
        survey["items"][1].pop("follow_up_at_or_below"); survey["items"][1].pop("follow_up_reason")
        assert not pipeline.registry.errors("survey", survey)  # still schema-valid: the schema is not the safety boundary
        rep, h = self._send_mutated(pipeline, row, hj, lambda it: (it.pop("follow_up_at_or_below"), it.pop("follow_up_reason")))
        assert rep.sent == 0 and rep.blocked_unsafe == 1 and h["state"] == "blocked_unsafe" and "follow_up_signal_missing" in h["state_detail"]
        assert pipeline.store.list_responses(survey_id=row["survey_id"]).total == 0

    def test_codex_reproduction_scale_min_3_with_threshold_1_is_blocked_at_send(self, scale_handoff):
        """Reviewer: scale_min 1 -> 3 with the threshold left at 1 made the follow-up unreachable, yet it was sent."""
        pipeline, row, hj = scale_handoff
        rep, h = self._send_mutated(pipeline, row, hj, lambda it: it.__setitem__("scale_min", 3))
        assert rep.sent == 0 and rep.blocked_unsafe == 1 and "scale_definition_mismatch" in h["state_detail"]

    @pytest.mark.parametrize("mutate,problem", [
        (lambda it: it.__setitem__("scale_max", 10), "scale_definition_mismatch"),
        (lambda it: it.__setitem__("scale_max", 4), "scale_definition_mismatch"),
        (lambda it: it.__setitem__("scale_min", 0), "scale_definition_mismatch"),
        (lambda it: it.__setitem__("scale_min", True), "scale_definition_mismatch"),            # bool masquerading as 1
        (lambda it: it.__setitem__("follow_up_at_or_below", 0), "follow_up_signal_missing"),     # unreachable threshold
        (lambda it: it.__setitem__("follow_up_at_or_below", 5), "follow_up_signal_missing"),     # everything follows up
        (lambda it: it.__setitem__("follow_up_at_or_below", True), "follow_up_signal_missing"),
        (lambda it: it.__setitem__("follow_up_reason", "could_not_reach_expert"), "follow_up_signal_missing"),
        (lambda it: it.__setitem__("follow_up_reason", None), "follow_up_signal_missing"),
        (lambda it: it.pop("follow_up_reason"), "follow_up_signal_missing"),
        (lambda it: it.__setitem__("options", [{"value": "yes", "label": "Yes"}, {"value": "no", "label": "No"}]), "scale_definition_mismatch"),
        (lambda it: (it.__setitem__("type", "survey-single-select"), it.pop("scale_min"), it.pop("scale_max"), it.pop("follow_up_at_or_below"), it.pop("follow_up_reason"),
                     it.__setitem__("options", [{"value": "yes", "label": "Yes"}, {"value": "no", "label": "No"}])), "item_type_mismatch"),
    ])
    def test_other_corrupt_scale_combinations_are_blocked(self, scale_handoff, mutate, problem):
        pipeline, row, hj = scale_handoff
        rep, h = self._send_mutated(pipeline, row, hj, mutate)
        assert rep.sent == 0 and rep.blocked_unsafe == 1 and problem in h["state_detail"], h["state_detail"]

    def test_untouched_scale_handoff_is_sent(self, scale_handoff):
        pipeline, row, hj = scale_handoff
        pipeline.clock.set(row["not_before"])
        rep = pipeline.broadcaster().tick()
        assert rep.blocked_unsafe == 0 and rep.sent == 1

    def test_validate_survey_text_checks_scale_definitions(self, scale_handoff):
        from mel_agent.generation.safety import validate_survey_text

        pipeline, row, hj = scale_handoff
        survey = hj["survey"]
        assert validate_survey_text(survey, survey["language"]) == []
        bad = json.loads(json.dumps(survey)); bad["items"][1]["scale_min"] = 3
        assert "scale_definition_mismatch" in validate_survey_text(bad, survey["language"])
        bad = json.loads(json.dumps(survey)); del bad["items"][1]["follow_up_at_or_below"]
        assert "follow_up_signal_missing" in validate_survey_text(bad, survey["language"])

    def test_construction_ignores_model_supplied_scale_fields(self, load_example, rules, calendar, settings, registry):
        from mel_agent.generation.generator import SurveyGenerator
        from mel_agent.generation.models import SurveyRequest
        from mel_agent.generation.providers import ScriptedProvider
        from mel_agent.rules.eligibility import decide

        insight = load_example("scenarios/1-mustard-aphid-spray/insight.json")
        d = decide(insight, rules, calendar)
        req = SurveyRequest.build(survey_id_for(insight["insight_id"]), insight, None, "en-IN", d.send_window, rules.asks_for_resolution("direct_action"))
        items = [{"intent": "did_action"}, {"intent": "advice_useful", "scale_min": 3, "scale_max": 100, "follow_up_at_or_below": 0, "follow_up_reason": "made_up"}]
        gen = SurveyGenerator(settings.model_copy(update={"generation_fallback_to_template": False, "generation_max_attempts": 1}), registry,
                              ScriptedProvider([{"items": items, "rationale": "ok"}]), fallback=None)
        result = gen.generate(req)
        assert result.accepted
        item = result.survey["items"][1]
        assert (item["scale_min"], item["scale_max"], item["follow_up_at_or_below"], item["follow_up_reason"]) == (1, 5, 1, "advice_did_not_work")

    def test_every_scale_intent_definition_validates_and_keeps_its_negative_signal(self):
        from mel_agent.generation.catalog import FOLLOW_UP_REASONS, QUESTION_CATALOG, item_problems, render_item

        for intent, spec in QUESTION_CATALOG.items():
            if spec["type"] != "survey-scale":
                continue
            lo, hi, thr, reason = spec["scale"]
            assert lo <= thr < hi and reason in FOLLOW_UP_REASONS and 0 <= lo < hi and hi - lo <= 9, intent
            item = render_item("q1", intent, "en-IN", {"asset": "crop", "concern": "", "expert": ""})
            assert item_problems(intent, item) == []
            assert item_problems(intent, {**item, "scale_min": lo + 1}) == ["scale_definition_mismatch"]


# =====================================================================================
# F3 (MEDIUM)  Ownership not rechecked immediately before inference
# =====================================================================================

class TestF3RecheckBeforeSend:
    def test_codex_reproduction_slow_client_construction_then_takeover_submits_nothing(self, pipeline, settings, registry, tmp_path, monkeypatch):
        """Reviewer: A passed the ownership check and reserved; during slow lazy client construction its lease
        expired and B scheduled the survey; A then still submitted one inference request."""
        import mel_agent.llm.bedrock as bedrock
        from mel_agent.delivery.clock import SimulatedClock
        from mel_agent.generation.generator import SurveyGenerator
        from mel_agent.generation.providers import BedrockProvider
        from mel_agent.llm.bedrock import BedrockInvoker
        from mel_agent.llm.budgeted import BudgetedInvoker
        from mel_agent.pipeline import Pipeline

        insight = _eligible_insight(pipeline.store, preferred_channel="whatsapp")
        sid = survey_id_for(insight["insight_id"])
        worker_b = Pipeline(settings, Store(pipeline.store.path), registry, clock=SimulatedClock(NOW))
        sent = {"n": 0}
        events: list[str] = []

        def slow_factory(s, service="bedrock-runtime", total_max_attempts=None):
            events.append("construct")
            with pipeline.store.write() as conn:  # the lease lapses while the client is being built...
                conn.execute("UPDATE generation_claims SET lease_until = ? WHERE insight_id = ?", (time.time() - 1, insight["insight_id"]))
            assert worker_b.process_insight(insight["insight_id"], NOW)["generation"]["status"] == "scheduled"  # ...and B takes over
            events.append("b_scheduled")
            c = _client(total_max_attempts)

            def converse(**_k):
                sent["n"] += 1
                raise AssertionError("inference submitted after ownership was lost")

            c.converse = converse
            return c

        monkeypatch.setattr(bedrock, "make_client", slow_factory)
        ctl = BudgetController(Store(tmp_path / "b.db"), _settings(), PRICING)
        pipeline.generator = SurveyGenerator(settings, registry, BedrockProvider(BudgetedInvoker(BedrockInvoker(_settings(), pricing=PRICING), ctl)), fallback=None)
        out = pipeline.process_insight(insight["insight_id"], NOW)["generation"]
        assert out["status"] == "lost_claim" and sent["n"] == 0 and events == ["construct", "b_scheduled"]
        assert _kinds(ctl) == ["reserve", "release"] and ctl.status().committed_usd == 0  # unused reservation came back
        with pipeline.store.read() as conn:
            assert conn.execute("SELECT COUNT(*) FROM handoffs WHERE survey_id = ?", (sid,)).fetchone()[0] == 1
        claim = pipeline.store.get_claim(insight["insight_id"])
        assert claim["status"] == "done" and claim["owner"] != "" and pipeline.store.get_handoff_for_survey(sid)["state"] == "scheduled"

    def test_recheck_applies_to_retries_with_an_already_built_client(self, tmp_path):
        from mel_agent.llm.budgeted import OwnershipLost

        client = _client()
        n = {"calls": 0}

        def throttle(**_k):
            n["calls"] += 1
            raise _error("ThrottlingException")

        client.converse = throttle
        inv, ctl = _invoker(tmp_path, client, app_attempts=3)
        checks = iter([True, True, True, False])  # attempt 1: start + pre-send ok; attempt 2: start ok, pre-send lost
        with pytest.raises(OwnershipLost):
            inv.converse("hi", max_tokens=10, may_continue=lambda: next(checks))
        assert n["calls"] == 1 and _kinds(ctl) == ["reserve", "release", "reserve", "release"] and ctl.status().committed_usd == 0

    def test_ownership_is_checked_twice_per_attempt_in_order(self, tmp_path):
        client = _client()
        client.converse = lambda **_k: _response()
        inv, ctl = _invoker(tmp_path, client)
        calls: list[str] = []

        def may_continue():
            calls.append(f"check:reserves={len([r for r in ctl.ledger() if r['kind'] == 'reserve'])}")
            return True

        inv.converse("hi", max_tokens=10, may_continue=may_continue)
        assert calls == ["check:reserves=0", "check:reserves=1"]  # before reserving, and again after the client with the reservation open

    def test_in_flight_request_after_loss_is_still_accounted(self, tmp_path):
        """Ownership lost AFTER submission does not release anything: the request happened."""
        client = _client()
        state = {"owner": True}

        def converse(**_k):
            state["owner"] = False  # lost while the request is in flight
            return _response(inp=10, out=5)

        client.converse = converse
        inv, ctl = _invoker(tmp_path, client)
        inv.converse("hi", max_tokens=10, may_continue=lambda: state["owner"])
        assert _kinds(ctl) == ["reserve", "settle"]

    def test_replacement_worker_is_untouched_by_the_release(self, tmp_path):
        """The superseded worker's release only touches ITS reservation."""
        client = _client()
        inv, ctl = _invoker(tmp_path, client)
        other = ctl.reserve(MODEL, 100, 10)  # the replacement worker's open reservation
        from mel_agent.llm.budgeted import OwnershipLost

        checks = iter([True, False])
        with pytest.raises(OwnershipLost):
            inv.converse("hi", max_tokens=10, may_continue=lambda: next(checks))
        state = ctl._summarise(ctl._ledger_rows(ctl.store._thread_conn()))["by_res"][other.reservation_id]
        assert state["final"] is None  # still open


# =====================================================================================
# F4 (MEDIUM)  Unsupported database versions were silently overwritten
# =====================================================================================

def _set_marker(path, value) -> None:
    con = sqlite3.connect(str(path))
    con.execute("INSERT INTO kv (k, v) VALUES ('schema_version', ?) ON CONFLICT (k) DO UPDATE SET v = excluded.v", (value,))
    con.commit(); con.close()


def _marker(path):
    con = sqlite3.connect(str(path))
    row = con.execute("SELECT v FROM kv WHERE k = 'schema_version'").fetchone()
    con.close()
    return None if row is None else row[0]


class TestF4SchemaVersionGate:
    @pytest.mark.parametrize("marker", ["4", "999", "not-a-version", "-1", "0", "", " 3", "3.0", "03", "1e3"])
    def test_codex_reproduction_unsupported_versions_are_refused_and_preserved(self, pipeline, tmp_path, marker):
        """Reviewer: initialisation unconditionally wrote schema_version=3 over 4, 999, 'not-a-version' and -1."""
        pipeline.store.checkpoint()
        path = tmp_path / "v.db"
        shutil.copy(pipeline.store.path, path)
        _set_marker(path, marker)
        before = sqlite3.connect(str(path))
        rows = before.execute("SELECT COUNT(*) FROM insights").fetchone()[0]
        schema = sorted(r[0] for r in before.execute("SELECT sql FROM sqlite_master WHERE sql IS NOT NULL"))
        before.close()
        with pytest.raises(StoreError, match="unsupported database schema version"):
            Store(path)
        assert _marker(path) == marker  # not downgraded, not rewritten
        after = sqlite3.connect(str(path))
        assert after.execute("SELECT COUNT(*) FROM insights").fetchone()[0] == rows
        assert sorted(r[0] for r in after.execute("SELECT sql FROM sqlite_master WHERE sql IS NOT NULL")) == schema
        after.close()

    def test_unsupported_marker_on_a_legacy_layout_is_refused_before_any_migration(self, pipeline, tmp_path):
        from test_regressions_codex3 import _downgrade_to_8bb4569

        pipeline.store.checkpoint()
        path = tmp_path / "legacy_future.db"
        shutil.copy(pipeline.store.path, path)
        _downgrade_to_8bb4569(str(path))
        _set_marker(path, "999")
        with pytest.raises(StoreError, match="999"):
            Store(path)
        raw = sqlite3.connect(str(path))
        assert "token" not in {r[1] for r in raw.execute("PRAGMA table_info(generation_claims)")}  # no partial migration
        assert raw.execute("SELECT v FROM kv WHERE k = 'schema_version'").fetchone()[0] == "999"
        raw.close()

    def test_supported_versions_open_and_end_at_three(self, pipeline, tmp_path):
        from test_regressions_codex3 import _downgrade_to_8bb4569

        pipeline.store.checkpoint()
        for label, prepare in (("fresh", None), ("legacy-unmarked", "legacy"), ("marker-1", "1"), ("marker-2", "2"), ("marker-3", "3")):
            path = tmp_path / f"{label}.db"
            if prepare is None:
                pass
            else:
                shutil.copy(pipeline.store.path, path)
                if prepare == "legacy":
                    _downgrade_to_8bb4569(str(path))
                else:
                    _set_marker(path, prepare)
            s = Store(path)
            assert s.schema_version() == 3, label
            with s.read() as conn:
                assert {"token", "lease_until"} <= {r[1] for r in conn.execute("PRAGMA table_info(generation_claims)")}, label

    def test_repeated_and_concurrent_startup_keep_version_three(self, pipeline, tmp_path):
        pipeline.store.checkpoint()
        path = tmp_path / "c.db"
        shutil.copy(pipeline.store.path, path)
        for _ in range(3):
            assert Store(path).schema_version() == 3
        barrier = threading.Barrier(5)
        out: list = []

        def start():
            barrier.wait(timeout=10)
            try:
                out.append(Store(path).schema_version())
            except BaseException as exc:  # noqa: BLE001
                out.append(exc)

        threads = [threading.Thread(target=start) for _ in range(5)]
        [t.start() for t in threads]; [t.join(timeout=60) for t in threads]
        assert out == [3] * 5

    def test_concurrent_startup_on_an_unsupported_database_all_refuse(self, pipeline, tmp_path):
        pipeline.store.checkpoint()
        path = tmp_path / "u.db"
        shutil.copy(pipeline.store.path, path)
        _set_marker(path, "7")
        barrier = threading.Barrier(4)
        out: list = []

        def start():
            barrier.wait(timeout=10)
            try:
                Store(path); out.append("opened")
            except StoreError:
                out.append("refused")

        threads = [threading.Thread(target=start) for _ in range(4)]
        [t.start() for t in threads]; [t.join(timeout=60) for t in threads]
        assert out == ["refused"] * 4 and _marker(path) == "7"

    def test_interrupted_migration_on_a_legacy_database_then_completes(self, pipeline, tmp_path):
        from test_regressions_codex3 import _downgrade_to_8bb4569

        pipeline.store.checkpoint()
        path = tmp_path / "i.db"
        shutil.copy(pipeline.store.path, path)
        _downgrade_to_8bb4569(str(path))

        class Crashing(Store):
            def _initialise(self):
                with self.write() as conn:
                    conn.execute("ALTER TABLE generation_claims ADD COLUMN token TEXT NOT NULL DEFAULT ''")
                    raise RuntimeError("power loss")

        with pytest.raises(RuntimeError):
            Crashing(path)
        assert _marker(path) is None
        assert Store(path).schema_version() == 3

    def test_api_startup_refuses_an_unsupported_database_clearly(self, pipeline, tmp_path, settings):
        from fastapi.testclient import TestClient
        from pydantic import SecretStr

        from mel_agent.main import create_app

        pipeline.store.checkpoint()
        path = tmp_path / "api.db"
        shutil.copy(pipeline.store.path, path)
        _set_marker(path, "42")
        app = create_app(settings.model_copy(update={"database_url": f"sqlite:///{path}", "operator_token": SecretStr("operator-token-for-tests-123")}))
        with pytest.raises(StoreError, match="42"):
            with TestClient(app):
                pass
        assert _marker(path) == "42"

    def test_marker_is_written_only_after_a_successful_check(self, tmp_path):
        s = Store(tmp_path / "fresh.db")
        assert s.schema_version() == 3
        from mel_agent.store.db import SUPPORTED_SCHEMA_VERSIONS, SCHEMA_VERSION

        assert SCHEMA_VERSION in SUPPORTED_SCHEMA_VERSIONS and max(SUPPORTED_SCHEMA_VERSIONS) == SCHEMA_VERSION
