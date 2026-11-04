"""API: contracts, validation, pagination bounds, safe defaults, no AWS from read paths."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from mel_agent.main import create_app


TOKEN = "test-operator-token-0123456789"


@pytest.fixture
def client(settings, tmp_path, monkeypatch):
    import boto3
    from pydantic import SecretStr

    def no_aws(*_a, **_k):
        raise AssertionError("API path reached boto3")

    monkeypatch.setattr(boto3, "client", no_aws)
    monkeypatch.setattr(boto3.Session, "client", no_aws)
    s = settings.model_copy(update={"database_url": f"sqlite:///{tmp_path / 'api.db'}", "operator_token": SecretStr(TOKEN)})
    with TestClient(create_app(s), headers={"X-Operator-Token": TOKEN}) as c:
        yield c


# ---------- H5: operator authorisation boundary ----------

PROTECTED = ["/insights", "/insights/I-000001", "/farmers", "/farmers/F-000001", "/decisions", "/surveys", "/handoffs", "/deliveries",
             "/responses", "/follow-up-queue", "/human-queue", "/stats", "/audit", "/budget", "/quarantine", "/runs/clock"]


@pytest.mark.parametrize("path", PROTECTED)
def test_protected_reads_require_token(client, path):
    assert client.get(path, headers={"X-Operator-Token": ""}).status_code == 401
    assert client.get(path, headers={"X-Operator-Token": TOKEN[:-1] + "x"}).status_code == 401
    r = client.get(path)  # fixture header = correct token
    assert r.status_code in (200, 404), (path, r.status_code)


@pytest.mark.parametrize("path", ["/runs/ingest", "/runs/decide", "/runs/generate", "/runs/evaluate", "/runs/process/I-000001"])
def test_workflow_routes_require_token(client, path):
    assert client.post(path, headers={"X-Operator-Token": ""}).status_code == 401
    assert client.post("/runs/broadcast", json={"until": "2026-11-02T00:00:00+05:30"}, headers={"X-Operator-Token": "wrong-token-value-1234567"}).status_code == 401


def test_healthz_and_docs_are_public(client):
    assert client.get("/healthz", headers={"X-Operator-Token": ""}).status_code == 200
    assert client.get("/openapi.json", headers={"X-Operator-Token": ""}).status_code == 200


def test_unconfigured_token_fails_closed(settings, tmp_path):
    s = settings.model_copy(update={"database_url": f"sqlite:///{tmp_path / 'noauth.db'}", "operator_token": None})
    with TestClient(create_app(s)) as c:
        assert c.get("/healthz").status_code == 200
        assert c.get("/insights").status_code == 503
        assert c.post("/runs/ingest").status_code == 503
        assert c.post("/runs/generate", json={"provider": "bedrock", "confirm_paid": True}).status_code == 503


def test_token_never_appears_in_responses(client):
    blob = client.get("/healthz").text + client.get("/openapi.json").text + client.get("/stats").text + client.get("/insights", headers={"X-Operator-Token": "nope"}).text
    assert TOKEN not in blob


@pytest.fixture
def loaded(client):
    r = client.post("/runs/ingest", json={"now": "2026-11-01T00:00:00+05:30"})
    assert r.status_code == 200 and r.json()["insights_lines"] == 6999
    assert client.post("/runs/decide").status_code == 200
    r = client.post("/runs/generate", json={"limit": 5})
    assert r.status_code == 200 and r.json()["handoffs_created"] == 5
    return client


def test_healthz_still_works_and_reports_safe_defaults(client):
    body = client.get("/healthz").json()
    assert body["status"] == "ok" and len(body["schemas_loaded"]) == 6
    assert body["bedrock"]["paid_inference_enabled"] is False and body["bedrock"]["generation_provider"] == "template"


def test_read_endpoints_and_pagination(loaded):
    c = loaded
    page = c.get("/insights", params={"limit": 3}).json()
    assert page["total"] == 6999 and len(page["items"]) == 3 and page["next_offset"] == 3
    assert c.get("/insights", params={"limit": 201}).status_code == 422
    assert c.get("/insights", params={"offset": -1}).status_code == 422
    assert c.get("/insights", params={"created_from": "2026-11-01"}).status_code == 422
    assert c.get("/insights/I-000001").json()["record"]["insight_id"] == "I-000001"
    assert c.get("/insights/I-999999").status_code == 404
    assert c.get("/insights/../etc").status_code in (404, 422)
    assert c.get("/farmers", params={"limit": 2}).json()["total"] == 300
    assert c.get("/farmers/F-000001").json()["record"]["farmer_id"] == "F-000001"
    assert c.get("/quarantine").json()["total"] == 50
    assert c.get("/decisions", params={"rule": "R9"}).status_code == 422
    assert c.get("/decisions", params={"decision": "survey", "limit": 1}).json()["total"] == 2628
    assert c.get("/human-queue").json()["total"] == 25


def test_decision_includes_external_no_survey_document(loaded, registry):
    c = loaded
    item = c.get("/decisions", params={"rule": "R1", "limit": 1}).json()["items"][0]
    d = c.get(f"/decisions/{item['insight_id']}").json()
    assert d["internal_reason"] == "junk_insight" and d["no_survey_schema_valid"] is True
    assert not registry.errors("no_survey", d["no_survey"])


def test_survey_handoff_and_bottom_sheet_views(loaded, registry):
    c = loaded
    s = c.get("/surveys", params={"limit": 1}).json()["items"][0]
    detail = c.get(f"/surveys/{s['survey_id']}", params={"render": "bottom_sheet", "channel": "app"}).json()
    assert not registry.errors("survey", detail["survey"]) and not registry.errors("bottom_sheet", detail["bottom_sheet"])
    assert c.get(f"/surveys/{s['survey_id']}", params={"render": "sms"}).status_code == 422
    h = c.get(f"/handoffs/{detail['handoff_id']}").json()
    assert not registry.errors("schedule_handoff", h["handoff"]) and h["state"] == "scheduled"
    assert c.get("/handoffs", params={"priority": "urgent"}).status_code == 422


def test_broadcast_moves_clock_forward_only_and_records_responses(loaded, registry):
    c = loaded
    h = c.get("/handoffs", params={"limit": 1}).json()["items"][0]
    assert c.post("/runs/broadcast", json={"until": "2020-01-01T00:00:00+05:30"}).status_code == 422
    assert c.post("/runs/broadcast", json={"until": "not a time"}).status_code == 422
    r = c.post("/runs/broadcast", json={"until": h["expires_at"], "step_minutes": 120})
    assert r.status_code == 200 and r.json()["totals"]["sent"] >= 1
    assert c.get("/runs/clock").json()["now"] >= h["expires_at"]
    resp = c.get("/responses", params={"limit": 5}).json()
    assert resp["total"] >= 1
    one = c.get(f"/responses/{resp['items'][0]['response_key']}").json()
    assert not registry.errors("response", one["record"])
    assert c.get("/deliveries", params={"channel": "fax"}).status_code == 422
    stats = c.get("/stats").json()
    assert stats["handoffs"] and stats["responses"]["by_status"]


def test_generate_is_bounded_and_bedrock_is_refused_by_default(loaded):
    c = loaded
    assert c.post("/runs/generate", json={"limit": 0}).status_code == 422
    assert c.post("/runs/generate", json={"limit": 5000}).status_code == 422
    assert c.post("/runs/generate", json={"language": "hindi"}).status_code == 422
    r = c.post("/runs/generate", json={"provider": "bedrock", "limit": 1, "confirm_paid": True})
    assert r.status_code == 403 and "disabled" in r.json()["detail"]
    r = c.post("/runs/generate", json={"insight_ids": ["I-000001", "bad id!"]})
    assert r.status_code == 422
    # L1: invalid enum values are rejected without echoing the submitted value
    r = c.post("/runs/generate", json={"provider": "bedrocks-SECRET-VALUE"})
    assert r.status_code == 422 and "SECRET-VALUE" not in r.text and "input" not in r.json()["detail"][0]
    assert c.post("/runs/generate", json={"unknown_field": 1}).status_code == 422


def test_bedrock_requires_explicit_confirmation_even_when_enabled(settings, tmp_path):
    from pydantic import SecretStr

    s = settings.model_copy(update={"database_url": f"sqlite:///{tmp_path / 'paid.db'}", "operator_token": SecretStr(TOKEN), "allow_paid_inference": True})
    with TestClient(create_app(s), headers={"X-Operator-Token": TOKEN}) as c:
        r = c.post("/runs/generate", json={"provider": "bedrock", "limit": 1})
        assert r.status_code == 403 and "confirm_paid" in r.json()["detail"]
        r = c.post("/runs/generate", json={"provider": "bedrock", "limit": 1, "confirm_paid": True})
        assert r.status_code == 409  # pipeline was started with the template provider: still no inference
        assert c.post("/runs/generate", json={"provider": "bedrock", "limit": 1, "confirm_paid": True}, headers={"X-Operator-Token": ""}).status_code == 401


def test_invalid_dates_and_steps_are_client_errors(loaded):
    c = loaded
    assert c.post("/runs/broadcast", json={"until": "2027-02-30T09:00:00+05:30"}).status_code == 422  # M4: impossible date
    assert c.post("/runs/broadcast", json={"until": "2027-01-01T09:00:00+05:30", "step_minutes": 0}).status_code == 422
    assert c.post("/runs/broadcast", json={"until": "2027-01-01T09:00:00+05:30", "step_minutes": 100000}).status_code == 422
    assert c.get("/insights", params={"created_from": "2026-02-30T00:00:00+05:30"}).status_code == 422
    assert c.post("/runs/ingest", json={"now": "2026-02-30T00:00:00+05:30"}).status_code == 422
    r = c.post("/runs/broadcast", json={"until": "2030-01-01T09:00:00+05:30", "step_minutes": 1})
    assert r.status_code == 422 and "ticks" in r.json()["detail"]


def test_process_unknown_insight_is_404(loaded):
    assert loaded.post("/runs/process/I-999999").status_code == 404


def test_process_single_insight_and_language_override(loaded, registry):
    c = loaded
    iid = c.get("/decisions", params={"decision": "survey", "limit": 1, "offset": 10}).json()["items"][0]["insight_id"]
    r = c.post(f"/runs/process/{iid}", json={"language": "en-IN"}).json()
    assert r["generation"]["status"] == "scheduled"
    assert c.get(f"/surveys/{r['generation']['survey_id']}").json()["language"] == "en-IN"
    again = c.post(f"/runs/process/{iid}").json()
    assert again["generation"]["status"] == "already_scheduled"


def test_evaluate_endpoint(loaded):
    r = loaded.post("/runs/evaluate")
    assert r.status_code == 200 and r.json()["eligibility"]["tp"] == 93


def test_budget_endpoint_reports_ledger(loaded):
    b = loaded.get("/budget").json()
    assert b["paid_inference_enabled"] is False and b["committed_usd"] == 0 and b["cutoff_usd"] == 225.0


def test_openapi_documents_every_route(client):
    spec = client.get("/openapi.json").json()
    paths = set(spec["paths"])
    for p in ("/healthz", "/insights", "/insights/{insight_id}", "/farmers", "/decisions", "/surveys/{survey_id}", "/handoffs", "/deliveries",
              "/responses", "/stats", "/budget", "/runs/ingest", "/runs/generate", "/runs/broadcast", "/runs/evaluate", "/follow-up-queue", "/human-queue"):
        assert p in paths, p
