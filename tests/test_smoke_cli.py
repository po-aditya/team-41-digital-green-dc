"""Fix 4: the smoke CLI fails cleanly on configuration problems, before any AWS call.

Every test here blocks real inference, so none of them can spend money.
"""

from __future__ import annotations

import json
import shutil

import pytest
from botocore.exceptions import ClientError

from mel_agent.llm import BedrockConfigError, InferenceResult, TokenUsage

SECRET = "AKIA_TEST_SECRET_VALUE_DO_NOT_PRINT"


@pytest.fixture
def smoke(load_script, monkeypatch, clean_mel_env):
    module = load_script("bedrock_smoke")

    def no_paid_calls(*_a, **_k):
        raise AssertionError("test attempted a real Bedrock call")

    monkeypatch.setattr(module.BedrockInvoker, "converse", no_paid_calls)
    return module


@pytest.fixture
def configured(monkeypatch, no_aws, settings, tmp_path):
    """Valid region, pricing file and (fake) credentials."""
    monkeypatch.setenv("MEL_BEDROCK_REGION", "us-west-2")
    monkeypatch.setenv("MEL_ALLOW_PAID_INFERENCE", "true")  # the explicit authorisation the CLI requires
    monkeypatch.setenv("MEL_DATABASE_URL", f"sqlite:///{tmp_path / 'ledger.db'}")
    pricing = tmp_path / "pricing.json"
    shutil.copy(settings.pricing_file, pricing)
    monkeypatch.setenv("MEL_PRICING_FILE", str(pricing))
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", SECRET)
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", SECRET)
    return pricing


def _run(smoke, capsys, *argv):
    code = smoke.main(list(argv))
    out = capsys.readouterr()
    assert SECRET not in out.out + out.err
    return code, out.err


def test_requires_confirmation(smoke, capsys):
    code, err = _run(smoke, capsys)
    assert code == 2 and "--yes" in err


def test_missing_region(smoke, capsys, configured, monkeypatch):
    monkeypatch.delenv("MEL_BEDROCK_REGION")
    code, err = _run(smoke, capsys, "--yes")
    assert code == 2
    assert "no AWS region" in err and "MEL_BEDROCK_REGION" in err


def test_invalid_settings(smoke, capsys, configured, monkeypatch):
    monkeypatch.setenv("MEL_BUDGET_STOP_USD", "300")  # above the 250 max
    monkeypatch.setenv("MEL_BEDROCK_TOTAL_MAX_ATTEMPTS", "not-a-number")
    code, err = _run(smoke, capsys, "--yes")
    assert code == 2
    assert "invalid configuration" in err and "MEL_BEDROCK_TOTAL_MAX_ATTEMPTS" in err
    assert "not-a-number" not in err  # input values are not echoed


def test_missing_pricing_file(smoke, capsys, configured, monkeypatch, tmp_path):
    monkeypatch.setenv("MEL_PRICING_FILE", str(tmp_path / "absent.json"))
    code, err = _run(smoke, capsys, "--yes")
    assert code == 2 and "pricing file not found" in err


@pytest.mark.parametrize(
    "content,expected",
    [
        ("{not json", "not valid JSON"),
        ('{"models": {}}', "no 'models'"),
        ('{"models": {"m": {"usd_per_million_tokens": {"input": 1}}}}', "'output'"),
        ("[]", "JSON object"),
    ],
)
def test_malformed_pricing_file(smoke, capsys, configured, content, expected):
    configured.write_text(content)
    code, err = _run(smoke, capsys, "--yes")
    assert code == 2 and expected in err


def test_missing_credentials(smoke, capsys, configured, monkeypatch):
    monkeypatch.delenv("AWS_ACCESS_KEY_ID")
    monkeypatch.delenv("AWS_SECRET_ACCESS_KEY")
    code, err = _run(smoke, capsys, "--yes")
    assert code == 2 and "no AWS credentials" in err


def test_bedrock_config_error(smoke, capsys, configured, monkeypatch):
    def raise_config(*_a, **_k):
        raise BedrockConfigError("No AWS region configured. Set MEL_BEDROCK_REGION")

    monkeypatch.setattr(smoke.BedrockInvoker, "converse", raise_config)
    code, err = _run(smoke, capsys, "--yes")
    assert code == 2 and "MEL_BEDROCK_REGION" in err


def test_bedrock_client_error(smoke, capsys, configured, monkeypatch):
    def denied(*_a, **_k):
        raise ClientError({"Error": {"Code": "AccessDeniedException", "Message": "no model access"}}, "Converse")

    monkeypatch.setattr(smoke.BedrockInvoker, "converse", denied)
    code, err = _run(smoke, capsys, "--yes")
    assert code == 1 and "AccessDeniedException" in err


def test_success_path_prints_usage_and_settles(smoke, capsys, configured, monkeypatch):
    def fake(self, *_a, **_k):
        return InferenceResult("us.anthropic.claude-haiku-5-5", "ok", "end_turn", TokenUsage(20, 4), 10.0, 8, 4.4e-06, retry_attempts=0)  # verified

    monkeypatch.setattr(smoke.BedrockInvoker, "converse", fake)
    code = smoke.main(["--yes"])
    out = json.loads(capsys.readouterr().out)
    assert code == 0 and out["usage"]["input_tokens"] == 20 and out["region"] == "us-west-2"
    assert out["budget"]["calls_settled"] == 1 and out["budget"]["open_reserved_usd"] == 0 and "warning" not in out


# ---------- H1: the CLI cannot bypass the application's paid-inference controls ----------

def _never(*_a, **_k):
    raise AssertionError("Bedrock converse must not be reached")


def test_disabled_paid_inference_blocks_before_pricing_and_credentials(smoke, capsys, configured, monkeypatch):
    monkeypatch.setenv("MEL_ALLOW_PAID_INFERENCE", "false")
    monkeypatch.setenv("MEL_PRICING_FILE", "/nonexistent.json")  # would fail later if reached
    monkeypatch.setattr(smoke.BedrockInvoker, "converse", _never)
    monkeypatch.setattr(smoke, "credentials_available", _never)
    code, err = _run(smoke, capsys, "--yes")
    assert code == 2 and "MEL_ALLOW_PAID_INFERENCE" in err


def test_unpriced_model_is_refused(smoke, capsys, configured, monkeypatch):
    monkeypatch.setattr(smoke.BedrockInvoker, "converse", _never)
    monkeypatch.setattr(smoke, "credentials_available", _never)
    code, err = _run(smoke, capsys, "--yes", "--model", "us.some.unpriced-model")
    assert code == 2 and "no pricing entry" in err


def test_exhausted_budget_blocks_before_credentials(smoke, capsys, configured, monkeypatch, tmp_path):
    from mel_agent.budget import BudgetController
    from mel_agent.config import Settings
    from mel_agent.llm.pricing import PricingTable, TokenUsage
    from mel_agent.store import Store

    monkeypatch.setenv("MEL_BUDGET_SAFETY_FACTOR", "1.0")
    s = Settings()
    ctl = BudgetController(Store.from_url(s.database_url), s, PricingTable.load(s.pricing_file))
    r = ctl.reserve(s.bedrock_model_id, 2_000_000_000, 0)  # $220 at Haiku regional pricing
    ctl.settle(r, TokenUsage(input_tokens=2_046_000_000))  # settles at ~$225.06: cutoff reached
    monkeypatch.setattr(smoke.BedrockInvoker, "converse", _never)
    monkeypatch.setattr(smoke, "credentials_available", _never)
    code, err = _run(smoke, capsys, "--yes")
    assert code == 2 and "budget state" in err


def test_missing_usage_is_not_settled_at_zero(smoke, capsys, configured, monkeypatch):
    def no_usage(self, *_a, **_k):
        return InferenceResult("us.anthropic.claude-haiku-5-5", "ok", "end_turn", None, 10.0, 8, None)

    monkeypatch.setattr(smoke.BedrockInvoker, "converse", no_usage)
    code = smoke.main(["--yes"])
    out = json.loads(capsys.readouterr().out)
    assert code == 0 and "warning" in out and out["usage_verified"] is False
    assert out["budget"]["unresolved_count"] == 1 and out["budget"]["unresolved_usd"] > 0 and out["budget"]["calls_settled"] == 0
