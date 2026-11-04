"""Regression tests for the 13 findings of the first independent (Codex) review.

Each section names the finding. Run against the audited commit 878e2e0 (the
repaired tree's conftest and this file copied into a worktree of that commit,
MEL_PARTICIPANT_PACK_DIR set, 240 s per class): 58 tests fail, 2 hang on the
baseline's own defects (the zero-step broadcaster loop in TestM4Timing and
process contention on the farmer cap in TestH4ConcurrentCap; the second M4 test
is therefore never reached), and 16 pass because they check properties the
baseline already satisfied (its existing advice/PII/question/language regexes,
pydantic bounds that already rejected NaN/negative/over-limit values, float
accounting within 1e-9, the retry marker path, cross-process reservations). The
passing ones are kept as guards, not as proof of a defect. Everything passes on
the repaired tree. No test reaches AWS or a real channel.
"""

from __future__ import annotations

import json
import multiprocessing as mp
import shutil
import sys
import threading
from pathlib import Path

import boto3
import pytest
from botocore.stub import Stubber

from mel_agent.budget import BudgetController, BudgetExceeded, BudgetUnavailable
from mel_agent.config import Settings
from mel_agent.llm.pricing import ModelPrice, PricingTable, TokenUsage
from mel_agent.rules.scheduling import survey_id_for
from mel_agent.store import Store
from mel_agent.time_utils import parse_ist

NOW = "2026-11-01T00:00:00+05:30"
MODEL = "m-test"
PRICING = PricingTable({MODEL: ModelPrice(input=1.0, output=2.0)})


def _settings(**over) -> Settings:
    base = {"allow_paid_inference": True, "budget_safety_factor": 1.0, "bedrock_model_id": MODEL, "bedrock_total_max_attempts": 1, "_env_file": None}
    base.update(over)
    return Settings(**base)


def _client(total_max_attempts: int = 1):
    from botocore.config import Config

    return boto3.client("bedrock-runtime", region_name="us-west-2", aws_access_key_id="testing", aws_secret_access_key="testing",
                        config=Config(retries={"total_max_attempts": total_max_attempts}))


def _response(text="ok", usage=True, inp=1000, out=500):
    r = {"output": {"message": {"role": "assistant", "content": [{"text": text}]}}, "stopReason": "end_turn", "metrics": {"latencyMs": 5},
         "ResponseMetadata": {"RetryAttempts": 0, "HTTPStatusCode": 200}}  # verified zero retries, as botocore reports
    if usage:
        r["usage"] = {"inputTokens": inp, "outputTokens": out, "totalTokens": inp + out}
    return r


def _eligible_insight(store: Store, **props):
    for row in store.iter_insights(only_valid=True):
        obj = json.loads(row["raw_json"])
        if (obj.get("verification") or {}).get("needed") and obj.get("severity") not in ("critical",) and obj.get("resolution_type") == "direct_action" \
                and all(obj.get(k) == v for k, v in props.items()):
            return obj
    raise AssertionError("no eligible insight")


# =====================================================================================
# C1  Missing Bedrock usage must never settle at $0 (adapter + controller integration)
# =====================================================================================

class TestC1MissingUsage:
    def test_parse_usage_distinguishes_missing_zero_and_verified(self):
        from mel_agent.llm.bedrock import parse_usage

        assert parse_usage(None, "ok") is None
        assert parse_usage({}, "ok") is None
        assert parse_usage({"inputTokens": 5}, "ok") is None                      # outputTokens missing
        assert parse_usage({"inputTokens": 5, "outputTokens": 0}, "ok") is None     # text but zero metered output
        assert parse_usage({"inputTokens": 5, "outputTokens": 0}, "") is not None   # verified zero output, empty reply
        assert parse_usage({"inputTokens": -1, "outputTokens": 2}, "ok") is None
        assert parse_usage({"inputTokens": "5", "outputTokens": 2}, "ok") is None
        assert parse_usage({"inputTokens": True, "outputTokens": 2}, "ok") is None
        ok = parse_usage({"inputTokens": 5, "outputTokens": 2}, "ok")
        assert ok is not None and ok.total_tokens == 7

    def test_response_without_usage_keeps_reservation_committed(self, tmp_path):
        from mel_agent.llm.bedrock import BedrockInvoker
        from mel_agent.llm.budgeted import BudgetedInvoker

        settings = _settings()
        ctl = BudgetController(Store(tmp_path / "b.db"), settings, PRICING)
        client = _client()
        client.converse = lambda **_k: _response(usage=False)  # the service model requires usage; a broken response omits it
        inv = BudgetedInvoker(BedrockInvoker(settings, pricing=PRICING, client=client), ctl)
        result = inv.converse("hi", max_tokens=1_000_000)  # estimate = $2 (1M output tokens at $2/M) + tiny input
        assert result.usage is None and result.usage_verified is False
        s = ctl.status()
        assert s.calls_settled == 0 and s.unresolved_count == 1 and s.unresolved_usd >= 2.0 and s.settled_usd == 0

    def test_five_calls_with_headroom_for_one_reach_the_provider_once(self, tmp_path):
        """Codex reproducer: five consecutive calls all reached the provider. Now only one may."""
        from mel_agent.llm.bedrock import BedrockInvoker
        from mel_agent.llm.budgeted import BudgetedInvoker

        settings = _settings(budget_stop_usd=3.0, budget_max_usd=3.0)
        ctl = BudgetController(Store(tmp_path / "b.db"), settings, PRICING)
        client = _client()
        reached = {"n": 0}

        def mocked(**_k):
            reached["n"] += 1
            return _response(usage=False)

        client.converse = mocked
        inv = BudgetedInvoker(BedrockInvoker(settings, pricing=PRICING, client=client), ctl)
        refused = 0
        for _ in range(5):
            try:
                inv.converse("hi", max_tokens=1_000_000)  # each estimate ~$2; headroom for exactly one
            except BudgetExceeded:
                refused += 1
        assert reached["n"] == 1 and refused == 4
        assert ctl.status().calls_refused == 4 and ctl.status().unresolved_count == 1

    def test_unparseable_reply_is_still_charged_and_accounted(self, load_example, rules, calendar, settings, registry):
        from mel_agent.generation.generator import SurveyGenerator
        from mel_agent.generation.models import SurveyRequest
        from mel_agent.generation.providers import BedrockProvider
        from mel_agent.llm.bedrock import InferenceResult
        from mel_agent.rules.eligibility import decide

        class Invoker:
            calls = 0

            def converse(self, *a, **k):
                Invoker.calls += 1
                return InferenceResult(MODEL, "this is not json", "end_turn", TokenUsage(100, 50), 10.0, 5, 0.0002)

        insight = load_example("scenarios/1-mustard-aphid-spray/insight.json")
        d = decide(insight, rules, calendar)
        req = SurveyRequest.build(survey_id_for(insight["insight_id"]), insight, None, "en-IN", d.send_window, "x")
        gen = SurveyGenerator(settings.model_copy(update={"generation_max_attempts": 2}), registry, BedrockProvider(Invoker()))
        result = gen.generate(req)
        assert Invoker.calls == 2 and result.accepted and result.source == "bedrock_fallback_template"
        assert result.failed_attempt_cost_usd == pytest.approx(0.0004) and result.usage["input_tokens"] == 200
        assert all("error" in a for a in result.attempts[:2])

    def test_transport_retries_are_reserved_for(self, tmp_path):
        settings = _settings(bedrock_total_max_attempts=3)
        ctl = BudgetController(Store(tmp_path / "b.db"), settings, PRICING)
        one = ctl.estimate_cost(MODEL, 1000, 1000, attempts=1)
        three = ctl.estimate_cost(MODEL, 1000, 1000, attempts=3)
        assert three == one * 3

    def test_manual_reconciliation_closes_an_unresolved_reservation(self, tmp_path):
        from mel_agent.budget import InvalidTransition

        ctl = BudgetController(Store(tmp_path / "b.db"), _settings(), PRICING)
        r = ctl.reserve(MODEL, 1_000_000, 0)
        ctl.mark_unresolved(r, "timeout")
        assert ctl.status().unresolved_usd == pytest.approx(1.0) and len(ctl.unresolved()) == 1
        ctl.reconcile(r.reservation_id, 0.25, "matched AWS bill line")
        s = ctl.status()
        assert s.unresolved_usd == 0 and s.settled_usd == pytest.approx(0.25) and ctl.unresolved() == []
        with pytest.raises(InvalidTransition):
            ctl.reconcile(r.reservation_id, 0.25, "twice")


# =====================================================================================
# H2  Unsafe survey content
# =====================================================================================

class TestH2UnsafeContent:
    @pytest.fixture
    def req(self, load_example, rules, calendar):
        from mel_agent.generation.models import SurveyRequest
        from mel_agent.rules.eligibility import decide

        insight = load_example("scenarios/1-mustard-aphid-spray/insight.json")
        d = decide(insight, rules, calendar)
        return SurveyRequest.build(survey_id_for(insight["insight_id"]), insight, None, "en-IN", d.send_window, "x")

    def _gen(self, settings, registry, items, rationale="ok"):
        from mel_agent.generation.generator import SurveyGenerator
        from mel_agent.generation.providers import ScriptedProvider

        # Free-form wording exists only behind the approval gate; these tests exercise the lexical
        # policy that still applies there (defence in depth). Review-2 tests cover the default path.
        return SurveyGenerator(settings.model_copy(update={"generation_fallback_to_template": False, "generation_max_attempts": 1,
                                                           "generation_allow_freeform": True}), registry,
                               ScriptedProvider([{"items": items, "rationale": rationale}]), fallback=None)

    def test_spray_petrol_label_cannot_be_scheduled(self, req, settings, registry):
        items = [{"type": "survey-confirm", "prompt": "Did you spray your mustard?", "options": [{"value": "yes", "label": "Spray petrol"}, {"value": "no"}]}]
        result = self._gen(settings, registry, items).generate(req)
        assert result.accepted and result.requires_approval  # catalogue label replaces the model's text; free-form needs approval
        assert [o["label"] for o in result.survey["items"][0]["options"]] == ["Yes", "No"]
        items = [{"type": "survey-confirm", "prompt": "Did you spray your mustard?", "options": [{"value": "spray_petrol", "label": "Spray petrol"}, {"value": "no"}]}]
        result = self._gen(settings, registry, items).generate(req)
        assert not result.accepted and result.attempts[0]["problems"] == ["malformed_provider_output"]

    @pytest.mark.parametrize("prompt,problem", [
        ("Did you spray petrol on the mustard?", "hazardous_substance"),
        ("Did you mix kerosene into the spray for the mustard?", "hazardous_substance"),
        ("Did you apply 500 ml of the spray to the mustard?", "unsupported_quantity"),
        ("Did you give 2 kg per acre to the mustard?", "unsupported_quantity"),
        ("Did you spray the mustard‮ as advised?", "control_or_format_character"),   # right-to-left override
        ("Did you spray the​ mustard as advised?", "control_or_format_character"),  # zero-width space
        ("Did you spray the mustаrd as advised?", "disallowed_script_or_symbol"),         # Cyrillic а homoglyph
        ("Did you spray the mustard? Visit example.com for more?", "leaks_instructions_or_contacts"),
        ("Spray the mustard again if aphids return?", "gives_new_advice"),
        ("Did you spray the mustard? You should also irrigate?", "gives_new_advice"),
        ("Did you spray the mustard and what is your Aadhaar number?", "asks_personal_info"),
        ("Did you spray the mustard", "prompt_not_a_question"),
    ])
    def test_english_prompt_policy(self, req, settings, registry, prompt, problem):
        items = [{"type": "survey-confirm", "prompt": prompt, "options": [{"value": "yes"}, {"value": "no"}]}]
        result = self._gen(settings, registry, items).generate(req)
        assert not result.accepted and problem in result.attempts[0]["problems"], result.attempts[0]

    @pytest.mark.parametrize("prompt,problem", [
        ("क्या आपने सरसों पर पेट्रोल छिड़का?", "hazardous_substance"),
        ("क्या आपने सरसों पर ५०० मिली दवा डाली?", "unsupported_quantity"),
        ("क्या आपने सरसों पर 2 किलो खाद डाली?", "unsupported_quantity"),
        ("सरसों पर फिर से छिड़काव करें।", "gives_new_advice"),
        ("क्या आपने सरसों पर छिड़काव किया और आपका आधार नंबर क्या है?", "asks_personal_info"),
        ("Did you spray the mustard?", "wrong_language"),
    ])
    def test_hindi_prompt_policy(self, load_example, rules, calendar, settings, registry, prompt, problem):
        from mel_agent.generation.models import SurveyRequest
        from mel_agent.rules.eligibility import decide

        insight = load_example("scenarios/1-mustard-aphid-spray/insight.json")
        d = decide(insight, rules, calendar)
        req = SurveyRequest.build(survey_id_for(insight["insight_id"]), insight, None, "hi-IN", d.send_window, "x")
        items = [{"type": "survey-confirm", "prompt": prompt, "options": [{"value": "yes"}, {"value": "no"}]}]
        result = self._gen(settings, registry, items).generate(req)
        assert not result.accepted and problem in result.attempts[0]["problems"], result.attempts[0]

    def test_rationale_is_policed_too(self, req, settings, registry):
        items = [{"type": "survey-confirm", "prompt": "Did you spray your mustard as advised?", "options": [{"value": "yes"}, {"value": "no"}]}]
        for bad, problem in [("see https://evil.example/x", "leaks_instructions_or_contacts"), ("note ‮ hidden", "control_or_format_character"),
                             ("farmer should apply 500 ml next time", "unsupported_quantity")]:
            result = self._gen(settings, registry, items, rationale=bad).generate(req)
            assert not result.accepted and problem in result.attempts[0]["problems"], (bad, result.attempts[0])

    def test_follow_up_only_on_negative_options_and_valid_reason(self, req, settings, registry):
        items = [{"type": "survey-confirm", "prompt": "Did you spray your mustard?", "options": [{"value": "yes", "follow_up": "advice_did_not_work"}, {"value": "better", "follow_up": "advice_did_not_work"}]}]
        assert not self._gen(settings, registry, items).generate(req).accepted  # 'better' is not a negative option
        items = [{"type": "survey-confirm", "prompt": "Did you spray your mustard?", "options": [{"value": "yes"}, {"value": "no", "follow_up": "made_up_reason"}]}]
        assert not self._gen(settings, registry, items).generate(req).accepted

    def test_scale_items_limited_to_ten_steps(self, req, settings, registry):
        items = [{"type": "survey-confirm", "prompt": "Did you spray your mustard?", "options": [{"value": "yes"}, {"value": "no"}]},
                 {"type": "survey-scale", "prompt": "How useful was the mustard advice?", "scale_min": 0, "scale_max": 100}]
        result = self._gen(settings, registry, items).generate(req)
        assert not result.accepted and "scale_out_of_policy" in result.attempts[0]["problems"]

    def test_broadcaster_blocks_unsafe_handoff_at_send_time(self, pipeline):
        """Defence in depth: a hand-off whose stored text violates policy is never sent."""
        insight = _eligible_insight(pipeline.store, preferred_channel="whatsapp")
        out = pipeline.process_insight(insight["insight_id"], NOW)
        hid = out["generation"]["handoff_id"]
        row = pipeline.store.get_handoff(hid)
        hj = json.loads(row["handoff_json"])
        hj["survey"]["items"][0]["prompt"] = "Did you spray petrol on the crop?"
        with pipeline.store.write() as conn:
            conn.execute("UPDATE handoffs SET handoff_json = ? WHERE handoff_id = ?", (json.dumps(hj), hid))
        pipeline.clock.set(row["not_before"])
        rep = pipeline.broadcaster().tick()
        assert rep.sent == 0 and rep.blocked_unsafe == 1
        assert pipeline.store.get_handoff(hid)["state"] == "blocked_unsafe"
        assert pipeline.store.list_responses(survey_id=row["survey_id"]).total == 0


# =====================================================================================
# H3  Malformed model output
# =====================================================================================

class TestH3MalformedOutput:
    def test_options_seven_does_not_raise_and_is_not_scheduled(self, pipeline, settings, registry):
        from mel_agent.generation.generator import SurveyGenerator
        from mel_agent.generation.providers import ScriptedProvider

        insight = _eligible_insight(pipeline.store)
        bad = {"items": [{"intent": "did_action", "options": 7}], "rationale": "x"}
        pipeline.generator = SurveyGenerator(settings.model_copy(update={"generation_fallback_to_template": False}), registry,
                                             ScriptedProvider([bad, bad]), fallback=None)
        out = pipeline.process_insight(insight["insight_id"], NOW)
        assert out["generation"]["status"] == "rejected"
        assert pipeline.store.get_handoff_for_survey(survey_id_for(insight["insight_id"])) is None
        validation = json.loads(pipeline.store.get_survey(survey_id_for(insight["insight_id"]))["validation_json"])
        assert all(a["problems"] == ["malformed_provider_output"] for a in validation["attempts"])

    @pytest.mark.parametrize("payload", [
        {"items": [{"type": "survey-confirm", "prompt": "Q?", "options": [{"value": "yes"}, 7]}]},
        {"items": [{"type": "survey-confirm", "prompt": 12, "options": [{"value": "yes"}, {"value": "no"}]}]},
        {"items": [{"type": "survey-scale", "prompt": "Q?", "scale_min": "1", "scale_max": 5}]},
        {"items": [{"type": "survey-scale", "prompt": "Q?", "scale_min": 1, "scale_max": 5, "follow_up_at_or_below": 1}]},  # reason missing
        {"items": ["not an item"]},
        {"items": "nope"},
        {"items": [{"type": "survey-confirm", "prompt": "Q?", "options": [{"value": "yes"}, {"value": "no"}, {"value": "not_yet"}]}]},  # confirm with 3
        {"items": [{"intent": 7}]},
        {"items": [{"intent": "did_action", "options": [{"value": "yes"}]}]},            # one option left
        {"items": [{"intent": "did_action", "options": [{"value": "yes"}, {"value": "better"}]}]},  # not this intent's option
        {"items": [{"intent": "did_action", "options": [7, 8]}]},
        {"items": [{"intent": "no_such_intent"}]},
        {"items": [{"intent": "did_action"}, {"intent": "did_action"}]},               # duplicate
    ])
    def test_bad_shapes_never_raise(self, load_example, rules, calendar, settings, registry, payload):
        from mel_agent.generation.generator import SurveyGenerator
        from mel_agent.generation.models import SurveyRequest
        from mel_agent.generation.providers import ScriptedProvider
        from mel_agent.rules.eligibility import decide

        insight = load_example("scenarios/1-mustard-aphid-spray/insight.json")
        d = decide(insight, rules, calendar)
        req = SurveyRequest.build(survey_id_for(insight["insight_id"]), insight, None, "en-IN", d.send_window, "x")
        gen = SurveyGenerator(settings.model_copy(update={"generation_fallback_to_template": False, "generation_max_attempts": 1}), registry,
                              ScriptedProvider([payload]), fallback=None)
        result = gen.generate(req)
        assert not result.accepted and result.survey is None

    def test_deterministic_provider_is_not_retried(self, load_example, rules, calendar, settings, registry):
        from mel_agent.generation.generator import SurveyGenerator
        from mel_agent.generation.models import SurveyRequest
        from mel_agent.generation.providers import TemplateProvider
        from mel_agent.rules.eligibility import decide

        insight = load_example("scenarios/1-mustard-aphid-spray/insight.json")
        d = decide(insight, rules, calendar)
        req = SurveyRequest.build(survey_id_for(insight["insight_id"]), insight, None, "xx-XX", d.send_window, "x")
        result = SurveyGenerator(settings.model_copy(update={"generation_max_attempts": 5}), registry, TemplateProvider()).generate(req)
        assert len(result.attempts) == 1 and result.attempts[0]["retryable"] is False

    def test_non_retryable_provider_error_stops_attempts(self, load_example, rules, calendar, settings, registry):
        from mel_agent.generation.generator import SurveyGenerator
        from mel_agent.generation.models import SurveyRequest
        from mel_agent.generation.providers import FailingProvider
        from mel_agent.rules.eligibility import decide

        insight = load_example("scenarios/1-mustard-aphid-spray/insight.json")
        d = decide(insight, rules, calendar)
        req = SurveyRequest.build(survey_id_for(insight["insight_id"]), insight, None, "en-IN", d.send_window, "x")
        failing = FailingProvider(retryable=False)
        result = SurveyGenerator(settings.model_copy(update={"generation_max_attempts": 4}), registry, failing).generate(req)
        assert failing.calls == 1 and result.accepted and result.source == "failing_fallback_template"


# =====================================================================================
# H4  Concurrent broadcasting and the farmer cap (threads and processes)
# =====================================================================================

def _two_due_handoffs_for_one_farmer(pipeline):
    """Two normal-priority eligible insights of one farmer with the same window start date."""
    by_farmer: dict[str, list] = {}
    for row in pipeline.store.iter_insights(only_valid=True):
        obj = json.loads(row["raw_json"])
        if obj.get("severity") in ("high", "critical") or obj.get("resolution_type") == "escalate_to_expert":
            continue
        d = pipeline.decide_one(row)
        if d.survey:
            by_farmer.setdefault(obj["farmer_id"], []).append((d.send_window.not_before, obj))
    for farmer, lst in by_farmer.items():
        lst.sort(key=lambda t: t[0])
        for (a_nb, a), (b_nb, b) in zip(lst, lst[1:]):
            if a_nb == b_nb:
                return a, b
    raise AssertionError("no pair")


class TestH4ConcurrentCap:
    def test_two_threads_separate_connections_one_send(self, pipeline, settings, registry):
        from mel_agent.delivery.clock import SimulatedClock
        from mel_agent.delivery.simulator import ScriptedSimulator
        from mel_agent.pipeline import Pipeline

        a, b = _two_due_handoffs_for_one_farmer(pipeline)
        pipeline.simulator = ScriptedSimulator(pipeline.outcome_codes, 1, {survey_id_for(a["insight_id"]): "silent", survey_id_for(b["insight_id"]): "silent"})
        ha = pipeline.process_insight(a["insight_id"], NOW)["generation"]["handoff_id"]
        hb = pipeline.process_insight(b["insight_id"], NOW)["generation"]["handoff_id"]
        pipeline.store.checkpoint()
        when = pipeline.store.get_handoff(ha)["not_before"]
        results = []
        barrier = threading.Barrier(2)

        def worker():
            p = Pipeline(settings, Store(pipeline.store.path), registry, clock=SimulatedClock(when))
            p.simulator = ScriptedSimulator(p.outcome_codes, 1, {survey_id_for(a["insight_id"]): "silent", survey_id_for(b["insight_id"]): "silent"})
            barrier.wait(timeout=30)
            results.append(p.broadcaster().tick())

        threads = [threading.Thread(target=worker) for _ in range(2)]
        [t.start() for t in threads]; [t.join() for t in threads]
        assert sum(r.sent for r in results) == 1
        states = sorted(pipeline.store.get_handoff(h)["state"] for h in (ha, hb))
        assert states == ["in_progress", "waiting_cap"]
        with pipeline.store.read() as conn:
            assert conn.execute("SELECT COUNT(*) FROM delivery_attempts WHERE sent_at IS NOT NULL").fetchone()[0] == 1

    def test_two_processes_one_send(self, pipeline):
        import concurrency_workers as cw
        from mel_agent.delivery.simulator import ScriptedSimulator

        a, b = _two_due_handoffs_for_one_farmer(pipeline)
        script = {survey_id_for(a["insight_id"]): "silent", survey_id_for(b["insight_id"]): "silent"}
        pipeline.simulator = ScriptedSimulator(pipeline.outcome_codes, 1, dict(script))
        ha = pipeline.process_insight(a["insight_id"], NOW)["generation"]["handoff_id"]
        hb = pipeline.process_insight(b["insight_id"], NOW)["generation"]["handoff_id"]
        pipeline.store.checkpoint()
        when = pipeline.store.get_handoff(ha)["not_before"]
        ctx = mp.get_context("spawn")
        barrier, q = ctx.Barrier(2), ctx.Queue()
        procs = [ctx.Process(target=cw.broadcaster_tick, args=(pipeline.store.path, when, script, barrier, q)) for _ in range(2)]
        [p.start() for p in procs]
        reports = [q.get(timeout=120) for _ in procs]
        [p.join(timeout=30) for p in procs]
        assert all(p.exitcode == 0 for p in procs)
        assert sum(r["sent"] for r in reports) == 1, reports
        states = sorted(Store(pipeline.store.path).get_handoff(h)["state"] for h in (ha, hb))
        assert states == ["in_progress", "waiting_cap"]

    def test_same_handoff_two_processes_single_attempt(self, pipeline):
        import concurrency_workers as cw
        from mel_agent.delivery.simulator import ScriptedSimulator

        insight = _eligible_insight(pipeline.store, preferred_channel="telegram")
        sid = survey_id_for(insight["insight_id"])
        pipeline.simulator = ScriptedSimulator(pipeline.outcome_codes, 1, {sid: "silent"})
        hid = pipeline.process_insight(insight["insight_id"], NOW)["generation"]["handoff_id"]
        pipeline.store.checkpoint()
        when = pipeline.store.get_handoff(hid)["not_before"]
        ctx = mp.get_context("spawn")
        barrier, q = ctx.Barrier(3), ctx.Queue()
        procs = [ctx.Process(target=cw.broadcaster_tick, args=(pipeline.store.path, when, {sid: "silent"}, barrier, q)) for _ in range(3)]
        [p.start() for p in procs]
        reports = [q.get(timeout=120) for _ in procs]
        [p.join(timeout=30) for p in procs]
        assert sum(r["sent"] for r in reports) == 1 and sum(r["claims_lost"] for r in reports) == 2, reports
        assert len([a for a in Store(pipeline.store.path).attempts_for_handoff(hid) if a["sent_at"]]) == 1


# =====================================================================================
# H6  Ledger corruption and monetary validation
# =====================================================================================

class TestH6Ledger:
    def test_negative_estimate_row_fails_closed(self, tmp_path):
        store = Store(tmp_path / "b.db")
        ctl = BudgetController(store, _settings(), PRICING)
        with store.write() as conn:
            conn.execute("INSERT INTO budget_ledger (entry_id, reservation_id, created_at, kind, model_id, estimated_usd) VALUES ('e', 'r', 'z', 'reserve', ?, -500)", (MODEL,))
        with pytest.raises(BudgetUnavailable):
            ctl.status()
        with pytest.raises(BudgetUnavailable):
            ctl.reserve(MODEL, 1, 1)

    @pytest.mark.parametrize("estimated,actual,kind", [("nan", None, "reserve"), ("inf", None, "reserve"), ("abc", None, "reserve"), (1.0, -1.0, "settle"), (1.0, None, "bogus_kind")])
    def test_malformed_rows_fail_closed(self, tmp_path, estimated, actual, kind):
        store = Store(tmp_path / "b.db")
        ctl = BudgetController(store, _settings(), PRICING)
        r = ctl.reserve(MODEL, 1, 1)
        # One row per (reservation, kind) is enforced by the schema (review-2 finding 4), so a second
        # 'reserve' row needs its own reservation id; the malformed value must still fail everything closed.
        rid = "r-malformed" if kind == "reserve" else r.reservation_id
        with store.write() as conn:
            conn.execute("INSERT INTO budget_ledger (entry_id, reservation_id, created_at, kind, model_id, estimated_usd, actual_usd) VALUES ('e', ?, 'z', ?, ?, ?, ?)",
                         (rid, kind, MODEL, estimated, actual))
        with pytest.raises(BudgetUnavailable):
            ctl.status()

    def test_invalid_transitions_rejected(self, tmp_path):
        from mel_agent.budget import InvalidTransition

        ctl = BudgetController(Store(tmp_path / "b.db"), _settings(), PRICING)
        r = ctl.reserve(MODEL, 1000, 10)
        ctl.release(r, "rejected")
        with pytest.raises(InvalidTransition):
            ctl.settle(r, TokenUsage(1, 1))
        with pytest.raises(InvalidTransition):
            ctl.release(r, "again")
        from mel_agent.budget.controller import Reservation
        ghost = Reservation("does-not-exist", MODEL, r.estimated_usd, "z")
        with pytest.raises(InvalidTransition):
            ctl.settle(ghost, TokenUsage(1, 1))

    @pytest.mark.parametrize("field,value", [("budget_max_usd", float("inf")), ("budget_stop_usd", float("nan")), ("budget_max_usd", -5),
                                             ("budget_max_usd", 10**9), ("budget_safety_factor", float("inf")), ("budget_chars_per_token", 0)])
    def test_settings_reject_nonfinite_or_absurd_money(self, field, value):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            Settings(_env_file=None, **{field: value})

    def test_fixed_precision_accounting(self, tmp_path):
        ctl = BudgetController(Store(tmp_path / "b.db"), _settings(), PRICING)
        for _ in range(1000):
            r = ctl.reserve(MODEL, 1, 0)                   # $0.000001 each
            ctl.settle(r, TokenUsage(input_tokens=1))
        assert ctl.status().settled_usd == pytest.approx(0.001, abs=1e-9)

    def test_concurrent_processes_never_exceed_cutoff(self, tmp_path):
        import concurrency_workers as cw

        db = tmp_path / "proc.db"
        Store(db)
        ctx = mp.get_context("spawn")
        barrier, q = ctx.Barrier(3), ctx.Queue()
        procs = [ctx.Process(target=cw.reserve_many, args=(str(db), 5, barrier, q)) for _ in range(3)]
        [p.start() for p in procs]
        granted = [q.get(timeout=120) for _ in procs]
        [p.join(timeout=30) for p in procs]
        assert sum(granted) == 7  # 7 x $30 = $210 fits under $225; the 8th would not
        ctl = BudgetController(Store(db), _settings(), PricingTable({"m": ModelPrice(1.0, 1.0)}))
        assert ctl.status().committed_usd <= 225.0


# =====================================================================================
# H7  Critical escalation precedence and incoherent records
# =====================================================================================

class TestH7Critical:
    def test_critical_and_casual_goes_to_human_queue(self, load_example, rules, calendar):
        from mel_agent.rules.eligibility import Reason, decide

        base = load_example("scenarios/4-cow-vet-escalation/insight.json")
        rec = dict(base, severity="critical", decision_episode_type="casual", asset={"name": None, "category": None, "growth_stage": None}, concern=None)
        d = decide(rec, rules, calendar)
        assert d.reason is Reason.CRITICAL_NEEDS_HUMAN_CALL and d.needs_human and d.details["contradictory_signals"]
        assert d.to_no_survey_contract()["reason_code"] == "needs_more_context"

    @pytest.mark.parametrize("mutation", [
        {"query_summary": "x"}, {"advice_summary": "........"}, {"query_summary": "aaaaaaaaaaaa"}, {"advice_summary": "Wheat"},
        {"query_summary": "Farmer asks about aphids on mustard.", "advice_summary": "Farmer asks about aphids on mustard."},
    ])
    def test_incoherent_but_schema_valid_records_do_not_reach_r8(self, load_example, rules, calendar, registry, mutation):
        from mel_agent.rules.eligibility import Reason, decide

        rec = dict(load_example("scenarios/1-mustard-aphid-spray/insight.json"), **mutation)
        assert not registry.errors("insight", rec)  # structurally complete
        d = decide(rec, rules, calendar)
        assert d.reason is Reason.JUNK_INSIGHT and not d.survey


# =====================================================================================
# M1  Channel fallback survives a crash between commit and the successor send
# =====================================================================================

class TestM1Recovery:
    def _scheduled(self, pipeline, channel="telegram"):
        from mel_agent.delivery.simulator import ScriptedSimulator

        insight = _eligible_insight(pipeline.store, preferred_channel=channel)
        sid = survey_id_for(insight["insight_id"])
        pipeline.simulator = ScriptedSimulator(pipeline.outcome_codes, 1, {sid: ["silent", "completed", "completed"]})
        hid = pipeline.process_insight(insight["insight_id"], NOW)["generation"]["handoff_id"]
        return hid, sid

    def test_crash_after_moved_on_before_successor_send_is_recovered(self, pipeline, monkeypatch):
        from mel_agent.delivery.broadcaster import Broadcaster

        hid, sid = self._scheduled(pipeline)
        row = pipeline.store.get_handoff(hid)
        hj = json.loads(row["handoff_json"])
        wait = hj["channel_order"][0]["wait_hours"]
        pipeline.clock.set(row["not_before"])
        b = pipeline.broadcaster()
        b.tick()
        pipeline.clock.advance(hours=wait + 1)
        real_send = Broadcaster._send
        calls = {"n": 0}

        def crash_on_successor(self, *a, **k):
            if k.get("marker") is not None:
                calls["n"] += 1
                raise RuntimeError("process killed")  # after moved_on + marker were committed
            return real_send(self, *a, **k)

        monkeypatch.setattr(Broadcaster, "_send", crash_on_successor)
        rep = b.tick()
        assert calls["n"] == 1 and rep.sent == 0
        attempts = pipeline.store.attempts_for_handoff(hid)
        assert any(a["state"] == "moved_on" for a in attempts) and any(a["state"] == "fallback_scheduled" for a in attempts)
        monkeypatch.undo()
        # A fresh broadcaster (restart) finds the durable successor marker and sends on the next channel.
        rep = pipeline.broadcaster().tick()
        assert rep.sent == 1
        attempts = pipeline.store.attempts_for_handoff(hid)
        assert any(a["channel_index"] == 1 and a["sent_at"] for a in attempts)
        assert not any(a["state"] == "fallback_scheduled" for a in attempts)

    def test_crash_after_failure_recorded_before_retry_is_recovered(self, pipeline, monkeypatch):
        from mel_agent.delivery.broadcaster import Broadcaster
        from mel_agent.delivery.simulator import ScriptedSimulator

        insight = _eligible_insight(pipeline.store, preferred_channel="voice")
        sid = survey_id_for(insight["insight_id"])
        pipeline.simulator = ScriptedSimulator(pipeline.outcome_codes, 1, {sid: ["voice_busy", "completed"]})
        hid = pipeline.process_insight(insight["insight_id"], NOW)["generation"]["handoff_id"]
        row = pipeline.store.get_handoff(hid)
        pipeline.clock.set(row["not_before"])
        b = pipeline.broadcaster()
        b.tick()                      # sent attempt 1 (voice_busy arrives after 2 minutes)
        pipeline.clock.advance(minutes=5)
        b.tick()                      # failure applied; retry marker written (due in 10 minutes)
        attempts = pipeline.store.attempts_for_handoff(hid)
        assert any(a["state"] == "retry_scheduled" for a in attempts)
        pipeline.clock.advance(minutes=15)
        monkeypatch.setattr(Broadcaster, "_send", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("killed")))
        b.tick()  # crashes inside _send: nothing sent, marker intact
        monkeypatch.undo()
        assert any(a["state"] == "retry_scheduled" for a in pipeline.store.attempts_for_handoff(hid))
        rep = pipeline.broadcaster().tick()
        assert rep.sent == 1 and any(a["delivery_attempt"] == 2 and a["sent_at"] for a in pipeline.store.attempts_for_handoff(hid))


# =====================================================================================
# M2  Duplicate generation and identifier collisions
# =====================================================================================

class TestM2Generation:
    def test_survey_ids_use_the_full_insight_id(self):
        assert survey_id_for("I-123456") == "S-123456"
        assert survey_id_for("X-123456") != survey_id_for("I-123456")
        assert survey_id_for("insight-123456") != survey_id_for("record-123456")
        ids = {survey_id_for(f"Z-{n:06d}") for n in range(5000)}
        assert len(ids) == 5000
        with pytest.raises(ValueError):
            survey_id_for("")

    def test_claim_blocks_second_insight_with_same_survey_id(self, pipeline, monkeypatch):
        import mel_agent.pipeline as pl

        rows = [json.loads(r["raw_json"]) for r in pipeline.store.iter_insights(only_valid=True)]
        eligible = [o for o in rows if pipeline.decide_one({"raw_json": json.dumps(o), "schema_valid": 1, "quarantine_reason": None}).survey][:2]
        a, b = eligible
        monkeypatch.setattr(pl, "survey_id_for", lambda _iid: "S-777777")  # force a collision
        out_a = pipeline.process_insight(a["insight_id"], NOW)
        out_b = pipeline.process_insight(b["insight_id"], NOW)
        assert out_a["generation"]["status"] == "scheduled"
        assert out_b["generation"]["status"] == "id_collision"
        assert pipeline.store.get_survey("S-777777")["insight_id"] == a["insight_id"]
        assert pipeline.store.list_handoffs().total == 1

    def test_concurrent_threads_generate_once(self, pipeline, settings, registry):
        from mel_agent.pipeline import Pipeline

        insight = _eligible_insight(pipeline.store)
        pipeline.store.checkpoint()
        barrier = threading.Barrier(4)
        results = []

        def worker():
            p = Pipeline(settings, Store(pipeline.store.path), registry)
            barrier.wait(timeout=30)
            results.append(p.process_insight(insight["insight_id"], NOW)["generation"]["status"])

        threads = [threading.Thread(target=worker) for _ in range(4)]
        [t.start() for t in threads]; [t.join() for t in threads]
        assert results.count("scheduled") == 1 and set(results) <= {"scheduled", "busy", "already_scheduled"}
        with pipeline.store.read() as conn:
            assert conn.execute("SELECT COUNT(*) FROM surveys").fetchone()[0] == 1
            assert conn.execute("SELECT COUNT(*) FROM handoffs").fetchone()[0] == 1
            assert conn.execute("SELECT COUNT(*) FROM audit_log WHERE event = 'generation:validated'").fetchone()[0] == 1

    def test_concurrent_processes_generate_once(self, pipeline):
        import concurrency_workers as cw

        insight = _eligible_insight(pipeline.store, preferred_channel="app")
        pipeline.store.checkpoint()
        ctx = mp.get_context("spawn")
        barrier, q = ctx.Barrier(3), ctx.Queue()
        procs = [ctx.Process(target=cw.generate_one, args=(pipeline.store.path, insight["insight_id"], barrier, q)) for _ in range(3)]
        [p.start() for p in procs]
        outs = [json.loads(q.get(timeout=120)) for _ in procs]
        [p.join(timeout=30) for p in procs]
        statuses = [o["status"] for o in outs]
        assert statuses.count("scheduled") == 1, statuses
        with Store(pipeline.store.path).read() as conn:
            assert conn.execute("SELECT COUNT(*) FROM handoffs").fetchone()[0] == 1

    def test_regeneration_never_resets_a_progressed_handoff(self, pipeline):
        from mel_agent.delivery.simulator import ScriptedSimulator

        insight = _eligible_insight(pipeline.store, preferred_channel="whatsapp")
        sid = survey_id_for(insight["insight_id"])
        pipeline.simulator = ScriptedSimulator(pipeline.outcome_codes, 1, {sid: "completed"})
        hid = pipeline.process_insight(insight["insight_id"], NOW)["generation"]["handoff_id"]
        pipeline.clock.set(pipeline.store.get_handoff(hid)["not_before"])
        b = pipeline.broadcaster(); b.tick(); pipeline.clock.advance(hours=6); b.tick()
        assert pipeline.store.get_handoff(hid)["state"] == "answered"
        before = pipeline.store.get_survey(sid)["survey_json"]
        # Force the claim back to 'failed' as an expired crashed worker would, then generate again.
        with pipeline.store.write() as conn:
            conn.execute("UPDATE generation_claims SET status = 'failed' WHERE insight_id = ?", (insight["insight_id"],))
        stats = pipeline.generate_and_schedule(NOW, insight_ids=[insight["insight_id"]])
        assert stats.handoffs_created == 0
        assert pipeline.store.get_handoff(hid)["state"] == "answered"
        assert pipeline.store.get_survey(sid)["survey_json"] == before

    def test_stale_claims_are_taken_over_only_after_the_real_time_lease(self, pipeline):
        import time

        insight = _eligible_insight(pipeline.store)
        sid = survey_id_for(insight["insight_id"])
        with pipeline.store.write() as conn:
            status, token = pipeline.store.claim_generation(conn, insight["insight_id"], sid, "dead-worker", "2026-11-01T00:00:00+05:30",
                                                            lease_seconds=300, wall=time.time())
        assert status == "claimed" and token
        # Season time moving on (even by months) does not expire a claim: the lease is wall-clock.
        assert pipeline.process_insight(insight["insight_id"], "2027-01-01T10:00:00+05:30")["generation"]["status"] == "busy"
        with pipeline.store.write() as conn:
            conn.execute("UPDATE generation_claims SET lease_until = ? WHERE insight_id = ?", (time.time() - 1, insight["insight_id"]))
        assert pipeline.process_insight(insight["insight_id"], NOW)["generation"]["status"] == "scheduled"
        with pipeline.store.write() as conn:  # the dead worker's token no longer finalises anything
            assert pipeline.store.finish_claim(conn, insight["insight_id"], token, "done", NOW) is False


# =====================================================================================
# M3  Malformed ingestion
# =====================================================================================

class TestM3Ingestion:
    def _mini_pack(self, tmp_path, settings, insights, insights_csv=None):
        from mel_agent.data.pack import PackPaths, pack_paths

        src = pack_paths(settings)
        root = tmp_path / "pack"
        (root / "data").mkdir(parents=True)
        (root / "json" / "rules").mkdir(parents=True)
        shutil.copytree(src.schemas_dir, root / "json" / "schemas")
        for f in (src.rules_json, src.outcome_codes_json):
            shutil.copy(f, root / "json" / "rules" / f.name)
        shutil.copy(src.crop_calendar_csv, root / "data" / "crop_calendar_bihar_rabi.csv")
        shutil.copy(src.farmers_csv, root / "data" / "farmers.csv")
        (root / "data" / "insights.jsonl").write_text("\n".join(insights) + "\n", encoding="utf-8")
        if insights_csv is not None:
            (root / "data" / "insights.csv").write_text(insights_csv, encoding="utf-8")
        return PackPaths(root)

    def _good(self, settings):
        from mel_agent.data.pack import pack_paths

        return json.loads(next(l for l in pack_paths(settings).insights_jsonl.open(encoding="utf-8") if '"I-000001"' in l))

    def test_quality_flag_array_does_not_crash(self, tmp_path, settings, registry):
        from mel_agent.data.ingest import Ingestor

        good = self._good(settings)
        weird = dict(good, insight_id="I-900001", quality_flag=["junk", "clean"])
        paths = self._mini_pack(tmp_path, settings, [json.dumps(good), json.dumps(weird)])
        store = Store(":memory:")
        stats = Ingestor(store, registry, paths).run(NOW)
        assert stats.quality_flag_counts.get("invalid_type") == 1
        assert store.get_insight("I-900001")["quarantine_reason"] == "schema_invalid"  # enum violation
        assert store.ingestion_complete()

    def test_short_csv_row_does_not_crash_and_is_counted(self, tmp_path, settings, registry):
        from mel_agent.data.ingest import Ingestor

        good = self._good(settings)
        csv_text = "insight_id,farmer_id,severity\nI-000001\nI-000001,F-000216,low,EXTRA\n"
        paths = self._mini_pack(tmp_path, settings, [json.dumps(good)], insights_csv=csv_text)
        store = Store(":memory:")
        stats = Ingestor(store, registry, paths).run(NOW)
        assert stats.csv_reconciliation["malformed_rows"] == 2 and stats.csv_reconciliation["status"] == "differences"
        assert store.ingestion_complete()

    def test_csv_without_insight_id_column_is_unusable_not_fatal(self, tmp_path, settings, registry):
        from mel_agent.data.ingest import Ingestor

        paths = self._mini_pack(tmp_path, settings, [json.dumps(self._good(settings))], insights_csv="a,b\n1,2\n")
        stats = Ingestor(Store(":memory:"), registry, paths).run(NOW)
        assert stats.csv_reconciliation["status"] == "csv_unusable"

    def test_failed_run_is_marked_and_blocks_downstream(self, tmp_path, settings, registry, monkeypatch):
        from mel_agent.data.ingest import IngestError, Ingestor
        from mel_agent.pipeline import IngestionIncomplete, Pipeline

        paths = self._mini_pack(tmp_path, settings, [json.dumps(self._good(settings))])
        store = Store(tmp_path / "partial.db")
        ing = Ingestor(store, registry, paths)
        monkeypatch.setattr(ing, "reconcile_csv", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("disk full")))
        with pytest.raises(IngestError):
            ing.run(NOW)
        run = store.latest_ingest_run()
        assert run["status"] == "failed" and run["error"] == "RuntimeError" and not store.ingestion_complete()
        p = Pipeline(settings.model_copy(update={"participant_pack_dir": paths.root}), store, registry)
        with pytest.raises(IngestionIncomplete):
            p.decide_all(NOW)
        with pytest.raises(IngestionIncomplete):
            p.generate_and_schedule(NOW)
        # A later successful run clears the block.
        monkeypatch.undo()
        Ingestor(store, registry, paths).run("2026-11-01T01:00:00+05:30")
        assert store.ingestion_complete() and p.decide_all(NOW)["decided"] == 1


# =====================================================================================
# M4  Timing inputs at the workflow boundary
# =====================================================================================

class TestM4Timing:
    def test_run_until_rejects_zero_step_and_huge_runs(self, pipeline):
        b = pipeline.broadcaster()
        with pytest.raises(ValueError):
            b.run_until("2026-11-02T00:00:00+05:30", step_minutes=0)
        with pytest.raises(ValueError):
            b.run_until("2026-11-02T00:00:00+05:30", step_minutes=5000)
        with pytest.raises(ValueError):
            b.run_until("2020-01-01T00:00:00+05:30", step_minutes=60)   # backwards
        with pytest.raises(ValueError):
            b.run_until("2030-01-01T00:00:00+05:30", step_minutes=1)    # too many ticks
        before = pipeline.clock.iso()
        reports = b.run_until("2026-11-01T02:00:00+05:30", step_minutes=60)
        assert len(reports) == 3 and pipeline.clock.iso() > before

    def test_valid_ist_rejects_impossible_dates(self):
        from fastapi import HTTPException

        from mel_agent.api.deps import valid_ist

        with pytest.raises(HTTPException) as exc:
            valid_ist("2027-02-30T09:00:00+05:30", "until")
        assert exc.value.status_code == 422
        assert valid_ist("2027-02-28T09:00:00+05:30", "until")
