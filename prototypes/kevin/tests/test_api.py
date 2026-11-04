"""REST API with FastAPI's TestClient. The model is replaced by FakeLLM."""
import uuid

import pytest
from fastapi.testclient import TestClient

from mel_agent import api, data, responses
from mel_agent.rules import parse_ts


@pytest.fixture
def client(fake_llm, monkeypatch):
    token = "kevin-offline-test-operator-token"
    monkeypatch.setenv("KEVIN_OPERATOR_TOKEN", token)
    for store in (api._results, api._flows):
        store.clear()
    api._responses.clear()
    api._follow_ups.clear()
    return TestClient(api.app, headers={"X-Operator-Token": token})


@pytest.fixture
def scheduled(client, insight):
    r = client.post("/v1/surveys", json=insight, params={"language": "en-IN"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "scheduled"
    return body


def _record(survey, answers, key_suffix="1"):
    sent = parse_ts(survey["send_window"]["not_before"])
    rec = responses.answered_record(survey, "app", 1, sent, sent.replace(hour=10), answers)
    rec["response_key"] = f"rk-{survey['survey_id']}-{key_suffix}"
    assert data.schema_errors("response", rec) == []
    return rec


def test_post_survey_returns_survey_and_handoff(client, insight):
    r = client.post("/v1/surveys", json=insight, params={"language": "en-IN"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "scheduled"
    assert data.schema_errors("survey", body["survey"]) == []
    assert data.schema_errors("schedule_handoff", body["handoff"]) == []
    sid = body["survey"]["survey_id"]
    assert client.get(f"/v1/surveys/{sid}").json()["survey"]["survey_id"] == sid
    assert client.get("/v1/surveys/S-999999").status_code == 404


def test_post_survey_for_info_only_insight_returns_no_survey(client, insight):
    insight["resolution_type"] = "generic_information"
    body = client.post("/v1/surveys", json=insight).json()
    assert body["status"] == "no_survey"
    assert body["handoff"] is None


def test_post_survey_rejects_bad_input(client):
    assert client.post("/v1/surveys", json={"insight_id": "I-1"}).status_code == 422
    assert client.post("/v1/surveys", json={"insight_id": "I-1", "farmer_id": "F-1"},
                       params={"language": "hindi"}).status_code == 422


def test_response_codes(client, scheduled):
    flow = scheduled["handoff"]["farmerchat_flow"]["flow_id"]
    rec = _record(scheduled["survey"], {"q1": "yes", "q2": "better"})
    url = f"/v1/surveys/{flow}/responses"

    first = client.post(url, json=rec)
    assert first.status_code == 201 and first.json() == {"outcome": "accepted"}

    again = client.post(url, json=rec)
    assert again.status_code == 200 and again.json() == {"outcome": "duplicate"}

    unknown = client.post(f"/v1/surveys/{uuid.uuid4()}/responses", json=rec)
    assert unknown.status_code == 404 and unknown.json() == {"outcome": "unknown_flow"}

    broken = dict(rec, response_key="rk-broken")
    del broken["status"]
    bad = client.post(url, json=broken)
    assert bad.status_code == 422 and bad.json()["outcome"] == "invalid_answer"

    wrong_survey = dict(rec, response_key="rk-wrong", survey_id="S-000001")
    assert client.post(url, json=wrong_survey).status_code == 422


def test_follow_ups(client, scheduled):
    flow = scheduled["handoff"]["farmerchat_flow"]["flow_id"]
    url = f"/v1/surveys/{flow}/responses"
    assert client.get("/v1/follow-ups").json() == []

    assert client.post(url, json=_record(scheduled["survey"], {"q1": "yes", "q2": "better"}, "ok")).status_code == 201
    assert client.get("/v1/follow-ups").json() == []

    assert client.post(url, json=_record(scheduled["survey"], {"q1": "yes", "q2": "worse"}, "bad")).status_code == 201
    fu = client.get("/v1/follow-ups").json()
    assert len(fu) == 1
    assert fu[0]["survey_id"] == scheduled["survey"]["survey_id"]
    assert fu[0]["reasons"] == ["crop_or_animal_damaged"]


@pytest.mark.parametrize("field,value", [
    ("farmer_id", "F-999999"),
    ("source_insight_ids", ["I-999999"]),
    ("language", "hi-IN"),
])
def test_response_rejects_cross_context_provenance(client, scheduled, field, value):
    flow = scheduled["handoff"]["farmerchat_flow"]["flow_id"]
    record = _record(scheduled["survey"], {"q1": "yes", "q2": "better"})
    record[field] = value
    assert client.post(f"/v1/surveys/{flow}/responses", json=record).status_code == 422
    assert api._responses == []


def test_generation_error_does_not_expose_internal_details(client, insight, monkeypatch):
    monkeypatch.setattr(api.pipeline, "process", lambda *a, **k: {
        "status": "error", "error": "private-sdk-detail", "survey": None, "handoff": None,
    })
    result = client.post("/v1/surveys", json=insight)
    assert result.status_code == 500
    assert "private-sdk-detail" not in result.text
