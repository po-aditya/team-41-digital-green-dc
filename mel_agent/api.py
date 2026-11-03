"""REST interface for the agent.

  uvicorn mel_agent.api:app --port 8001

POST /v1/surveys            insight JSON (+ ?language=hi-IN) -> decision, survey, hand-off
GET  /v1/surveys/{id}       a generated result
POST /v1/surveys/{flow_id}/responses   answer record (validated against response.schema.json)
GET  /v1/follow-ups         answers that reported a bad outcome
GET  /health
"""
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse

from . import data, pipeline, rules

app = FastAPI(title="FarmerChat MEL Survey Agent", version="0.1.0")
_results: dict[str, dict] = {}
_flows: dict[str, str] = {}
_responses: list[dict] = []
_follow_ups: list[dict] = []


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/v1/surveys")
def create_survey(insight: dict, language: str | None = Query(None, pattern=r"^[a-z]{2,3}-[A-Z]{2}$"),
                  policy: str = Query(rules.DEFAULT_POLICY, pattern="^(baseline|calibrated)$")):
    if not isinstance(insight.get("insight_id"), str) or not isinstance(insight.get("farmer_id"), str):
        raise HTTPException(422, "insight_id and farmer_id are required strings")
    r = pipeline.process(insight, language=language, policy=policy)
    if r["survey"]:
        _results[r["survey"]["survey_id"]] = r
    if r["handoff"]:
        _flows[r["handoff"]["farmerchat_flow"]["flow_id"]] = r["survey"]["survey_id"]
    code = 500 if r["status"] == "error" else 200
    return JSONResponse(r, status_code=code)


@app.get("/v1/surveys/{survey_id}")
def get_survey(survey_id: str):
    if survey_id not in _results:
        raise HTTPException(404, "unknown survey")
    return _results[survey_id]


@app.post("/v1/surveys/{flow_id}/responses", status_code=201)
def post_response(flow_id: str, record: dict):
    sid = _flows.get(flow_id)
    if not sid:
        return JSONResponse({"outcome": "unknown_flow"}, status_code=404)
    errs = data.schema_errors("response", record)
    if errs or record.get("survey_id") != sid:
        return JSONResponse({"outcome": "invalid_answer", "errors": errs[:5] or ["survey_id does not match flow"]},
                            status_code=422)
    if any(r["response_key"] == record["response_key"] for r in _responses):
        return JSONResponse({"outcome": "duplicate"}, status_code=200)
    _responses.append(record)
    if record.get("needs_follow_up"):
        _follow_ups.append({"survey_id": sid, "farmer_id": record["farmer_id"],
                            "source_insight_ids": record["source_insight_ids"],
                            "reasons": record["follow_up_reasons"]})
    return {"outcome": "accepted"}


@app.get("/v1/follow-ups")
def follow_ups():
    return _follow_ups
