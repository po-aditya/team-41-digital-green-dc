import pytest
from pydantic import ValidationError

from mel_agent.config import Settings
from mel_agent.llm import credentials_available

def test_defaults_without_any_env(no_aws, clean_mel_env):
    s = Settings(_env_file=None)
    assert s.budget_max_usd == 250.0
    assert s.budget_stop_usd == 225.0
    assert s.bedrock_model_id
    assert s.bedrock_total_max_attempts == 3
    # No region is assumed: it must be configured explicitly (README documents this).
    assert s.bedrock_region is None
    assert s.resolved_bedrock_region is None
    assert s.pricing_file.is_file()


def test_settings_have_no_credential_fields():
    names = set(Settings.model_fields)
    assert not any("secret" in n or "access_key" in n or "session_token" in n for n in names)


def test_env_overrides(monkeypatch):
    monkeypatch.setenv("MEL_BEDROCK_REGION", "us-east-1")
    monkeypatch.setenv("MEL_BEDROCK_MODEL_ID", "us.anthropic.claude-sonnet-5-5")
    monkeypatch.setenv("MEL_BUDGET_STOP_USD", "100")
    s = Settings(_env_file=None)
    assert s.resolved_bedrock_region == "us-east-1"
    assert s.bedrock_model_id == "us.anthropic.claude-sonnet-5-5"
    assert s.budget_stop_usd == 100.0


def test_region_falls_back_to_aws_env(monkeypatch):
    monkeypatch.delenv("MEL_BEDROCK_REGION", raising=False)
    monkeypatch.delenv("AWS_REGION", raising=False)
    monkeypatch.setenv("AWS_DEFAULT_REGION", "ap-south-1")
    assert Settings(_env_file=None).resolved_bedrock_region == "ap-south-1"


def test_stop_threshold_cannot_exceed_max():
    with pytest.raises(ValidationError):
        Settings(budget_max_usd=100, budget_stop_usd=150, _env_file=None)


def test_credentials_absent_is_reported_not_raised(no_aws):
    assert credentials_available() is False


def test_bedrock_client_requires_region(no_aws):
    from mel_agent.llm import BedrockConfigError
    from mel_agent.llm.bedrock import make_client

    with pytest.raises(BedrockConfigError):
        make_client(Settings(_env_file=None))
