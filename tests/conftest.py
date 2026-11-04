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


@pytest.fixture(autouse=True)
def no_network(request, monkeypatch):
    """Fail any test that tries a real HTTP call through botocore (stubs and event hooks still work).

    Tests marked ``bedrock`` (the opt-in paid smoke test) are exempt."""
    if request.node.get_closest_marker("bedrock"):
        return
    import botocore.httpsession

    def forbidden(self, request):  # noqa: ARG001
        raise AssertionError(f"test attempted a real network call to {getattr(request, 'url', '?')}")

    monkeypatch.setattr(botocore.httpsession.URLLib3Session, "send", forbidden)


# ---------- pipeline fixtures (new in the MVP phases) ----------

PACK_START = "2026-11-01T00:00:00+05:30"


@pytest.fixture(scope="session")
def ingested_db_path(tmp_path_factory, settings) -> Path:
    """One ingestion of the whole pack per session; tests copy the SQLite file."""
    from mel_agent.pipeline import Pipeline
    from mel_agent.store import Store

    path = tmp_path_factory.mktemp("db") / "ingested.db"
    store = Store(path)
    Pipeline(settings, store).ingest(PACK_START)
    getattr(store, "checkpoint", lambda: None)()  # fold the WAL into the file so copies are complete
    return path


@pytest.fixture
def fresh_store(tmp_path, ingested_db_path):
    """A private copy of the ingested database for one test."""
    import shutil

    from mel_agent.store import Store

    dst = tmp_path / "mel.db"
    shutil.copy(ingested_db_path, dst)
    return Store(dst)


@pytest.fixture
def pipeline(settings, fresh_store, registry):
    from mel_agent.delivery.clock import SimulatedClock
    from mel_agent.pipeline import Pipeline

    return Pipeline(settings, fresh_store, registry, clock=SimulatedClock(PACK_START))


@pytest.fixture(scope="session")
def rules(settings):
    from mel_agent.data.pack import Rules, pack_paths

    return Rules.load(pack_paths(settings))


@pytest.fixture(scope="session")
def outcome_codes(settings):
    from mel_agent.data.pack import OutcomeCodes, pack_paths

    return OutcomeCodes.load(pack_paths(settings))


@pytest.fixture(scope="session")
def calendar(settings):
    import csv

    from mel_agent.data.pack import pack_paths
    from mel_agent.rules.eligibility import CropCalendar

    with pack_paths(settings).crop_calendar_csv.open(encoding="utf-8", newline="") as fh:
        return CropCalendar.from_rows(list(csv.DictReader(fh)))


@pytest.fixture(scope="session")
def golden_cases(settings):
    from mel_agent.data.pack import pack_paths

    return [json.loads(l) for l in pack_paths(settings).golden_jsonl.read_text(encoding="utf-8").splitlines() if l.strip()]


@pytest.fixture(scope="session")
def scenario_dirs(pack_json):
    return sorted(p for p in (pack_json / "scenarios").iterdir() if p.is_dir())


@pytest.fixture
def load_example(pack_json):
    """Return a deep copy of a pack example so tests can mutate it freely."""

    def _load(rel: str) -> dict:
        return copy.deepcopy(json.loads((pack_json / rel).read_text(encoding="utf-8")))

    return _load
