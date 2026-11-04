"""Offline tests for the Bedrock adapter and pricing. No network, no cost."""

from __future__ import annotations

import os

import boto3
import pytest
from botocore.stub import Stubber

from mel_agent.config import Settings
from mel_agent.llm import BedrockInvoker, BudgetState, ModelPrice, PricingTable, TokenUsage, budget_state


@pytest.fixture
def stubbed_runtime():
    client = boto3.client(
        "bedrock-runtime",
        region_name="us-west-2",
        aws_access_key_id="testing",
        aws_secret_access_key="testing",
    )
    with Stubber(client) as stub:
        yield client, stub


def _converse_response(text="ok", inp=12, out=3):
    return {
        "output": {"message": {"role": "assistant", "content": [{"text": text}]}},
        "stopReason": "end_turn",
        "usage": {"inputTokens": inp, "outputTokens": out, "totalTokens": inp + out},
        "metrics": {"latencyMs": 321},
    }


def test_converse_captures_usage_latency_and_cost(stubbed_runtime):
    client, stub = stubbed_runtime
    settings = Settings(bedrock_model_id="m-1", _env_file=None)
    pricing = PricingTable({"m-1": ModelPrice(input=1.0, output=5.0)})
    stub.add_response(
        "converse",
        _converse_response(inp=1000, out=200),
        {
            "modelId": "m-1",
            "messages": [{"role": "user", "content": [{"text": "hi"}]}],
            "inferenceConfig": {"maxTokens": 16},
        },
    )
    result = BedrockInvoker(settings, pricing=pricing, client=client).converse("hi", max_tokens=16)

    assert result.text == "ok"
    assert result.usage.input_tokens == 1000 and result.usage.output_tokens == 200
    assert result.usage.total_tokens == 1200
    assert result.server_latency_ms == 321
    assert result.latency_ms >= 0
    # 1000 * $1/M + 200 * $5/M
    assert result.estimated_cost_usd == pytest.approx(0.002)


def test_unknown_model_cost_is_none_not_guessed(stubbed_runtime):
    client, stub = stubbed_runtime
    stub.add_response("converse", _converse_response())
    result = BedrockInvoker(
        Settings(bedrock_model_id="unpriced", _env_file=None), pricing=PricingTable({}), client=client
    ).converse("hi")
    assert result.estimated_cost_usd is None


def test_temperature_and_system_passed_when_set(stubbed_runtime):
    client, stub = stubbed_runtime
    stub.add_response(
        "converse",
        _converse_response(),
        {
            "modelId": "m",
            "messages": [{"role": "user", "content": [{"text": "hi"}]}],
            "inferenceConfig": {"maxTokens": 8, "temperature": 0.0},
            "system": [{"text": "be brief"}],
        },
    )
    BedrockInvoker(Settings(_env_file=None), client=client).converse(
        "hi", system="be brief", model_id="m", max_tokens=8, temperature=0.0
    )


def test_pricing_file_loads_and_is_sourced(settings):
    table = PricingTable.load(settings.pricing_file)
    assert "AWS Price List API" in table.meta["source"]
    price = table.price_for(settings.bedrock_model_id)
    assert price is not None, "default model must have a pricing entry"
    assert price.input > 0 and price.output > 0


def test_cache_tokens_without_cache_price_raise():
    with pytest.raises(ValueError):
        ModelPrice(input=1, output=1).cost(TokenUsage(cache_read_tokens=10))


@pytest.mark.parametrize(
    "spent,expected",
    [(0, BudgetState.OK), (224.99, BudgetState.OK), (225, BudgetState.STOP), (249.9, BudgetState.STOP), (250, BudgetState.EXCEEDED)],
)
def test_budget_state_thresholds(spent, expected):
    assert budget_state(spent, stop_usd=225, max_usd=250) is expected


# ---------- opt-in paid smoke test ----------


@pytest.mark.bedrock
@pytest.mark.skipif(os.environ.get("MEL_RUN_BEDROCK_SMOKE") != "1", reason="set MEL_RUN_BEDROCK_SMOKE=1 to allow a paid call")
def test_bedrock_live_smoke():
    """Opt-in paid call. Goes through the same gates as the application: it is skipped unless
    MEL_ALLOW_PAID_INFERENCE is true, and the call is reserved and settled in the ledger."""
    from mel_agent.budget import BudgetController
    from mel_agent.llm.budgeted import BudgetedInvoker
    from mel_agent.store import Store

    settings = Settings()
    if not settings.allow_paid_inference:
        pytest.skip("paid inference is disabled (MEL_ALLOW_PAID_INFERENCE); not authorised")
    pricing = PricingTable.load(settings.pricing_file)
    controller = BudgetController(Store.from_url(settings.database_url), settings, pricing)
    before = controller.status()
    result = BudgetedInvoker(BedrockInvoker(settings, pricing=pricing), controller).converse("Reply with exactly one word: ok", max_tokens=16)
    assert result.text.strip()
    after = controller.status()
    assert after.calls_settled + after.unresolved_count == before.calls_settled + before.unresolved_count + 1
