"""R3: docker-compose.yml forwards every documented region variable (static check).

Docker is not installed on the dev machine; this checks the file, not a running stack.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from mel_agent.config import Settings

ROOT = Path(__file__).resolve().parents[1]
REGION_VARS = ["MEL_BEDROCK_REGION", "AWS_REGION", "AWS_DEFAULT_REGION"]  # documented precedence
CREDENTIAL_VARS = ["AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"]


@pytest.fixture(scope="module")
def api_environment() -> list[str]:
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
    env = compose["services"]["api"]["environment"]
    assert isinstance(env, list), "environment should be a list of names to forward"
    return env


@pytest.mark.parametrize("var", REGION_VARS)
def test_region_variables_are_forwarded_by_name(api_environment, var):
    assert var in api_environment


@pytest.mark.parametrize("var", CREDENTIAL_VARS)
def test_credentials_forwarded_by_name_only(api_environment, var):
    assert var in api_environment
    assert not any(e.startswith(f"{var}=") for e in api_environment)


def test_no_inline_values_for_forwarded_variables(api_environment):
    # Pass-through only: a value here would override the shell and could embed a secret.
    assert all("=" not in e for e in api_environment), api_environment


def test_readme_documents_same_region_variables_in_same_order():
    readme = (ROOT / "README.md").read_text()
    line = next(l for l in readme.splitlines() if l.startswith("Lookup order:"))
    assert re.findall(r"`([A-Z_]+)`", line) == REGION_VARS


# ---------- precedence is applied by the app, including when Compose forwards empty values ----------


@pytest.mark.parametrize(
    "env,expected",
    [
        ({"MEL_BEDROCK_REGION": "eu-west-1", "AWS_REGION": "us-east-1", "AWS_DEFAULT_REGION": "ap-south-1"}, "eu-west-1"),
        ({"AWS_REGION": "us-east-1", "AWS_DEFAULT_REGION": "ap-south-1"}, "us-east-1"),
        ({"AWS_DEFAULT_REGION": "ap-south-1"}, "ap-south-1"),
        ({"MEL_BEDROCK_REGION": "", "AWS_REGION": "", "AWS_DEFAULT_REGION": "ap-south-1"}, "ap-south-1"),
        ({"MEL_BEDROCK_REGION": "", "AWS_REGION": "", "AWS_DEFAULT_REGION": ""}, None),
        ({}, None),
    ],
)
def test_region_precedence(monkeypatch, clean_mel_env, env, expected):
    for var in REGION_VARS:
        monkeypatch.delenv(var, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    assert Settings(_env_file=None).resolved_bedrock_region == expected
