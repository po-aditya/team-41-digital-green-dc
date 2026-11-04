"""Fix 4: the smoke CLI fails cleanly on configuration problems, before any AWS call.

Every test here blocks real inference, so none of them can spend money.
"""

from __future__ import annotations

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


def test_success_path_prints_usage(smoke, capsys, configured, monkeypatch):
    def fake(self, *_a, **_k):
        return InferenceResult("m", "ok", "end_turn", TokenUsage(20, 4), 10.0, 8, 4.4e-06)

    monkeypatch.setattr(smoke.BedrockInvoker, "converse", fake)
    code = smoke.main(["--yes"])
    out = capsys.readouterr().out
    assert code == 0 and '"input_tokens": 20' in out and '"region": "us-west-2"' in out
