from fastapi.testclient import TestClient

from mel_agent.config import Settings
from mel_agent.contracts import SchemaName


def test_package_and_entrypoint_import():
    import mel_agent.main

    assert mel_agent.main.app.title == "FarmerChat MEL Survey Agent"


def test_startup_loads_schemas_and_healthz_ok(settings):
    from mel_agent.main import create_app

    with TestClient(create_app(settings)) as client:  # runs lifespan startup
        r = client.get("/healthz")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["env"] == "test"
    assert sorted(body["schemas_loaded"]) == sorted(n.value for n in SchemaName)


def test_healthz_works_without_aws_credentials(monkeypatch):
    for var in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN", "AWS_PROFILE"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", "/nonexistent")
    monkeypatch.setenv("AWS_CONFIG_FILE", "/nonexistent")
    from mel_agent.main import create_app

    with TestClient(create_app(Settings(_env_file=None))) as client:
        assert client.get("/healthz").status_code == 200


def test_startup_fails_fast_when_schemas_missing(tmp_path):
    import pytest

    from mel_agent.contracts import SchemaLoadError
    from mel_agent.main import create_app

    app = create_app(Settings(participant_pack_dir=tmp_path, _env_file=None))
    with pytest.raises(SchemaLoadError):
        with TestClient(app):
            pass
