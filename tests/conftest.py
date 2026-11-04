from __future__ import annotations

import copy
import importlib.util
import json
import os
from pathlib import Path

import pytest

from mel_agent.config import Settings
from mel_agent.contracts import SchemaRegistry


@pytest.fixture(scope="session")
def settings() -> Settings:
    return Settings(app_env="test", _env_file=None)


@pytest.fixture(scope="session")
def pack_json(settings) -> Path:
    path = settings.participant_pack_dir / "json"
    if not path.is_dir():
        pytest.fail(f"Participant pack not found at {settings.participant_pack_dir}; set MEL_PARTICIPANT_PACK_DIR")
    return path


@pytest.fixture(scope="session")
def registry(settings) -> SchemaRegistry:
    return SchemaRegistry(settings.schemas_dir)


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"


@pytest.fixture
def load_script():
    """Import a file from scripts/ as a module (scripts/ is not a package)."""

    def _load(name: str):
        spec = importlib.util.spec_from_file_location(f"script_{name}", SCRIPTS_DIR / f"{name}.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    return _load


@pytest.fixture
def no_aws(monkeypatch):
    """Strip every credential and region source boto3 could use (env, ~/.aws, IMDS, containers)."""
    for var in (
        "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN", "AWS_PROFILE",
        "AWS_REGION", "AWS_DEFAULT_REGION", "AWS_CONTAINER_CREDENTIALS_RELATIVE_URI",
        "AWS_CONTAINER_CREDENTIALS_FULL_URI", "AWS_WEB_IDENTITY_TOKEN_FILE",
    ):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", "/nonexistent")
    monkeypatch.setenv("AWS_CONFIG_FILE", "/nonexistent")
    monkeypatch.setenv("AWS_EC2_METADATA_DISABLED", "true")


@pytest.fixture
def clean_mel_env(monkeypatch):
    """Remove MEL_* variables and stop Settings reading a local .env file."""
    for key in list(os.environ):
        if key.startswith("MEL_"):
            monkeypatch.delenv(key)
    monkeypatch.setitem(Settings.model_config, "env_file", None)


@pytest.fixture
def load_example(pack_json):
    """Return a deep copy of a pack example so tests can mutate it freely."""

    def _load(rel: str) -> dict:
        return copy.deepcopy(json.loads((pack_json / rel).read_text(encoding="utf-8")))

    return _load
