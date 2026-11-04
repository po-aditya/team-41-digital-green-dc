"""Budget controller: cutoff, reservations, settlement, fail-closed paths, concurrency, invoker integration."""

from __future__ import annotations

import threading

import boto3
import pytest
from botocore.exceptions import ReadTimeoutError
from botocore.stub import Stubber

from mel_agent.budget import BudgetController, BudgetExceeded, BudgetUnavailable, PaidInferenceDisabled
from mel_agent.config import Settings
from mel_agent.llm.bedrock import BedrockInvoker
from mel_agent.llm.budgeted import BudgetedInvoker
from mel_agent.llm.pricing import ModelPrice, PricingTable, TokenUsage
from mel_agent.store import Store

MODEL = "m-test"
# $1 per million input, $2 per million output -> 1000 in + 500 out = $0.002 actual
PRICING = PricingTable({MODEL: ModelPrice(input=1.0, output=2.0)})


def _settings(**over) -> Settings:
    base = {"allow_paid_inference": True, "budget_max_usd": 250.0, "budget_stop_usd": 225.0, "budget_safety_factor": 1.0, "_env_file": None}
    base.update(over)
    return Settings(**base)


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "budget.db")


def test_disabled_by_default_fails_closed(store):
    ctl = BudgetController(store, Settings(_env_file=None), PRICING)
    assert ctl.status().paid_inference_enabled is False
    with pytest.raises(PaidInferenceDisabled):
        ctl.reserve(MODEL, 10, 10)
    assert ctl.status().committed_usd == 0


def test_missing_pricing_refuses(store):
    with pytest.raises(BudgetUnavailable):
        BudgetController(store, _settings(), None).reserve(MODEL, 10, 10)
    with pytest.raises(BudgetUnavailable):
        BudgetController(store, _settings(), PRICING).reserve("unpriced-model", 10, 10)


def test_reserve_settle_release_unresolved(store):
    ctl = BudgetController(store, _settings(), PRICING)
    r = ctl.reserve(MODEL, 1_000_000, 1_000_000)  # estimate $3
    assert ctl.status().open_reserved_usd == pytest.approx(3.0)
    actual = ctl.settle(r, TokenUsage(input_tokens=1000, output_tokens=500))
    assert actual == pytest.approx(0.002)
    s = ctl.status()
    assert s.settled_usd == pytest.approx(0.002) and s.open_reserved_usd == 0 and s.calls_settled == 1
    r2 = ctl.reserve(MODEL, 1_000_000, 0)
    ctl.release(r2, "rejected before inference")
    r3 = ctl.reserve(MODEL, 1_000_000, 0)
    ctl.mark_unresolved(r3, "timeout")
    s = ctl.status()
    assert s.unresolved_usd == pytest.approx(1.0) and s.committed_usd == pytest.approx(1.002)


def test_settle_without_usage_keeps_estimate_committed(store):
    ctl = BudgetController(store, _settings(), PRICING)
    r = ctl.reserve(MODEL, 2_000_000, 0)  # $2
    ctl.settle(r, None)
    assert r.outcome == "unresolved" and ctl.status().committed_usd == pytest.approx(2.0)


def test_cutoff_is_enforced_exactly(store):
    ctl = BudgetController(store, _settings(), PRICING)
    r = ctl.reserve(MODEL, 100_000_000, 0)  # $100
    ctl.settle(r, TokenUsage(input_tokens=100_000_000))  # $100 actual
    r = ctl.reserve(MODEL, 100_000_000, 0)
    ctl.settle(r, TokenUsage(input_tokens=100_000_000))  # committed $200
    ctl.reserve(MODEL, 25_000_000, 0)                  # +$25 -> exactly 225 is allowed (not exceeded)
    with pytest.raises(BudgetExceeded, match="cutoff"):
        ctl.reserve(MODEL, 1, 0)                        # anything more is refused
    s = ctl.status()
    assert s.calls_refused == 1 and s.state == "stop" and s.committed_usd == pytest.approx(225.0)


def test_estimate_is_conservative(store):
    ctl = BudgetController(store, _settings(budget_safety_factor=1.25, budget_chars_per_token=3.0), PRICING)
    assert ctl.estimate_tokens("a" * 300) == 101
    assert float(ctl.estimate_cost(MODEL, 1_000_000, 1_000_000)) == pytest.approx(3.0 * 1.25)
    # transport retries multiply the reservation; settlement later releases the surplus
    assert float(ctl.estimate_cost(MODEL, 1_000_000, 1_000_000, attempts=3)) == pytest.approx(3.0 * 1.25 * 3)


def test_ledger_is_durable_across_controller_instances(tmp_path):
    store = Store(tmp_path / "durable.db")
    ctl = BudgetController(store, _settings(), PRICING)
    r = ctl.reserve(MODEL, 50_000_000, 0)
    ctl.settle(r, TokenUsage(input_tokens=50_000_000))
    again = BudgetController(Store(tmp_path / "durable.db"), _settings(), PRICING)
    assert again.status().settled_usd == pytest.approx(50.0)


def test_concurrent_reservations_never_exceed_cutoff(tmp_path):
    store = Store(tmp_path / "conc.db")
    ctl = BudgetController(store, _settings(), PRICING)
    granted, refused = [], []

    def worker():
        try:
            granted.append(ctl.reserve(MODEL, 30_000_000, 0))  # $30 each; at most 7 fit under $225
        except BudgetExceeded:
            refused.append(1)

    threads = [threading.Thread(target=worker) for _ in range(20)]
    [t.start() for t in threads]; [t.join() for t in threads]
    assert len(granted) == 7 and len(refused) == 13
    assert ctl.status().committed_usd <= 225.0


def test_charge_context_manager_marks_unresolved_on_exception(store):
    ctl = BudgetController(store, _settings(), PRICING)
    with pytest.raises(RuntimeError):
        with ctl.charge(MODEL, "x" * 300, 100):
            raise RuntimeError("network died")
    assert ctl.status().unresolved_usd > 0


def test_corrupt_ledger_fails_closed(store):
    ctl = BudgetController(store, _settings(), PRICING)
    r = ctl.reserve(MODEL, 1000, 10)
    with store.write() as conn:
        conn.execute("INSERT INTO budget_ledger (entry_id, reservation_id, created_at, kind, model_id, estimated_usd, actual_usd) VALUES ('e', ?, 'z', 'settle', ?, 0, NULL)", (r.reservation_id, MODEL))
    with pytest.raises(BudgetUnavailable):
        ctl.status()
    with pytest.raises(BudgetUnavailable):
        ctl.reserve(MODEL, 1, 1)


# ---------- BudgetedInvoker with a stubbed Bedrock client (no network) ----------

def _client(total_max_attempts: int = 1):
    from botocore.config import Config

    return boto3.client("bedrock-runtime", region_name="us-west-2", aws_access_key_id="testing", aws_secret_access_key="testing",
                        config=Config(retries={"total_max_attempts": total_max_attempts}))


def _response(inp=1000, out=500):
    # ResponseMetadata.RetryAttempts is what botocore attaches to every real response; the paid-call boundary
    # settles only on a verified zero (review-4 finding 1), so the stub must carry it too.
    return {"output": {"message": {"role": "assistant", "content": [{"text": "ok"}]}}, "stopReason": "end_turn",
            "usage": {"inputTokens": inp, "outputTokens": out, "totalTokens": inp + out}, "metrics": {"latencyMs": 5},
            "ResponseMetadata": {"RetryAttempts": 0, "HTTPStatusCode": 200}}


def test_budgeted_invoker_reserves_then_settles_actual(store):
    settings = _settings(bedrock_model_id=MODEL)
    client = _client()
    ctl = BudgetController(store, settings, PRICING)
    inv = BudgetedInvoker(BedrockInvoker(settings, pricing=PRICING, client=client), ctl)
    with Stubber(client) as stub:
        stub.add_response("converse", _response())
        result = inv.converse("hi", max_tokens=100)
    assert result.text == "ok"
    s = ctl.status()
    assert s.calls_settled == 1 and s.open_reserved_usd == 0 and s.settled_usd == pytest.approx(0.002)


def test_budgeted_invoker_refuses_when_cutoff_reached_without_calling_aws(store):
    settings = _settings(bedrock_model_id=MODEL)
    client = _client()
    ctl = BudgetController(store, settings, PRICING)
    r = ctl.reserve(MODEL, 225_000_000, 0); ctl.settle(r, TokenUsage(input_tokens=225_000_000))
    inv = BudgetedInvoker(BedrockInvoker(settings, pricing=PRICING, client=client), ctl)
    with Stubber(client) as stub:  # no response registered: any call would raise
        with pytest.raises(BudgetExceeded):
            inv.converse("hi", max_tokens=10)
        stub.assert_no_pending_responses()


def test_budgeted_invoker_disabled_setting_blocks_before_aws(store):
    settings = Settings(bedrock_model_id=MODEL, _env_file=None)
    client = _client()
    inv = BudgetedInvoker(BedrockInvoker(settings, pricing=PRICING, client=client), BudgetController(store, settings, PRICING))
    with Stubber(client):
        with pytest.raises(PaidInferenceDisabled):
            inv.converse("hi")


def test_budgeted_invoker_releases_on_rejected_request(store):
    settings = _settings(bedrock_model_id=MODEL)
    client = _client()
    ctl = BudgetController(store, settings, PRICING)
    inv = BudgetedInvoker(BedrockInvoker(settings, pricing=PRICING, client=client), ctl)
    with Stubber(client) as stub:
        stub.add_client_error("converse", "AccessDeniedException", "no model access", response_meta={"RetryAttempts": 0})  # verified zero retries
        with pytest.raises(Exception):
            inv.converse("hi", max_tokens=10)
    assert ctl.status().committed_usd == 0


def test_budgeted_invoker_keeps_estimate_on_timeout(store, monkeypatch):
    settings = _settings(bedrock_model_id=MODEL)
    client = _client()
    ctl = BudgetController(store, settings, PRICING)
    inv = BudgetedInvoker(BedrockInvoker(settings, pricing=PRICING, client=client), ctl)

    def timeout(*_a, **_k):
        raise ReadTimeoutError(endpoint_url="https://bedrock")

    monkeypatch.setattr(client, "converse", timeout)
    with pytest.raises(ReadTimeoutError):
        inv.converse("hi", max_tokens=10)
    assert ctl.status().unresolved_usd > 0


def test_each_application_retry_is_a_separate_reservation(store):
    """Retrying at the generator level cannot bypass the budget: every attempt reserves again."""
    settings = _settings(bedrock_model_id=MODEL)
    client = _client()
    ctl = BudgetController(store, settings, PRICING)
    r = ctl.reserve(MODEL, 224_000_000, 0); ctl.settle(r, TokenUsage(input_tokens=224_000_000))  # $224 spent
    inv = BudgetedInvoker(BedrockInvoker(settings, pricing=PRICING, client=client), ctl)
    with Stubber(client) as stub:
        stub.add_response("converse", _response(inp=100, out=100))
        inv.converse("hi", max_tokens=100)                      # fits: tiny estimate
        with pytest.raises(BudgetExceeded):
            inv.converse("x" * 3_000_000, max_tokens=100)       # the "retry" with a big prompt is refused
        stub.assert_no_pending_responses()
