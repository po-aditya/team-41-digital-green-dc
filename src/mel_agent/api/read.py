"""Read-only inspection endpoints. None of these trigger generation, delivery or AWS calls."""

from __future__ import annotations

import json
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query

from mel_agent.api.deps import LimitQ, OffsetQ, get_pipeline, get_store, not_found, page_or_422, require_operator, valid_id, valid_ist, valid_language
from mel_agent.contracts import SchemaName
from mel_agent.delivery.bottom_sheet import render_bottom_sheet
from mel_agent.pipeline import Pipeline
from mel_agent.rules.eligibility import Outcome
from mel_agent.store import Store

# Every record-level and operational read requires the operator token (see api/deps.py).
router = APIRouter(dependencies=[Depends(require_operator)])


# ---------- insights ----------

@router.get("/insights", tags=["insights"], summary="List ingested insights (paginated, stable order)")
def list_insights(store: Annotated[Store, Depends(get_store)], limit: LimitQ = 50, offset: OffsetQ = 0,
                  farmer_id: str | None = None, resolution_type: str | None = None, asset_name: str | None = None,
                  concern: str | None = None, created_from: str | None = None, created_to: str | None = None,
                  schema_valid: bool | None = None) -> dict[str, Any]:
    if farmer_id:
        valid_id(farmer_id, "farmer_id")
    return page_or_422(store.list_insights, farmer_id=farmer_id, resolution_type=resolution_type, asset_name=asset_name, concern=concern,
                       created_from=valid_ist(created_from, "created_from"), created_to=valid_ist(created_to, "created_to"),
                       schema_valid=schema_valid, limit=limit, offset=offset)


@router.get("/insights/{insight_id}", tags=["insights"], summary="One insight with its original record and decision")
def get_insight(insight_id: str, store: Annotated[Store, Depends(get_store)]) -> dict[str, Any]:
    row = store.get_insight(valid_id(insight_id, "insight_id"))
    if row is None:
        raise not_found("insight")
    try:
        record = json.loads(row["raw_json"])
    except json.JSONDecodeError:
        record = None
    decision = store.get_decision(insight_id)
    return {"insight_id": row["insight_id"], "schema_valid": bool(row["schema_valid"]), "quarantine_reason": row["quarantine_reason"],
            "source": {"file": row["source_file"], "line_no": row["line_no"], "content_hash": row["content_hash"]},
            "record": record, "decision": _decision_view(decision)}


@router.get("/quarantine", tags=["insights"], summary="Rows that failed ingestion checks")
def list_quarantine(store: Annotated[Store, Depends(get_store)], limit: LimitQ = 50, offset: OffsetQ = 0) -> dict[str, Any]:
    return page_or_422(store.list_quarantine, limit=limit, offset=offset)


# ---------- farmers ----------

@router.get("/farmers", tags=["farmers"])
def list_farmers(store: Annotated[Store, Depends(get_store)], limit: LimitQ = 50, offset: OffsetQ = 0,
                 district: str | None = None, preferred_channel: str | None = None) -> dict[str, Any]:
    return page_or_422(store.list_farmers, district=district, preferred_channel=preferred_channel, limit=limit, offset=offset)


@router.get("/farmers/{farmer_id}", tags=["farmers"])
def get_farmer(farmer_id: str, store: Annotated[Store, Depends(get_store)]) -> dict[str, Any]:
    row = store.get_farmer(valid_id(farmer_id, "farmer_id"))
    if row is None:
        raise not_found("farmer")
    return {"farmer_id": row["farmer_id"], "record": json.loads(row["raw_json"]), "source": {"file": row["source_file"], "line_no": row["line_no"]}}


# ---------- decisions ----------

def _decision_view(d: dict[str, Any] | None) -> dict[str, Any] | None:
    if d is None:
        return None
    out = {k: d[k] for k in ("insight_id", "farmer_id", "decision", "rule", "internal_reason", "external_reason_code", "reason_text", "decided_at")}
    out["details"] = json.loads(d["details_json"]) if d.get("details_json") else {}
    return out


@router.get("/decisions", tags=["decisions"], summary="Eligibility decisions")
def list_decisions(store: Annotated[Store, Depends(get_store)], limit: LimitQ = 50, offset: OffsetQ = 0,
                   decision: str | None = Query(None, pattern="^(survey|no_survey|quarantined)$"),
                   rule: str | None = Query(None, pattern="^R[0-8]$"), farmer_id: str | None = None) -> dict[str, Any]:
    return page_or_422(store.list_decisions, decision=decision, rule=rule, farmer_id=farmer_id, limit=limit, offset=offset)


@router.get("/decisions/{insight_id}", tags=["decisions"], summary="One decision, with the external no_survey document when applicable")
def get_decision(insight_id: str, store: Annotated[Store, Depends(get_store)], pipeline: Annotated[Pipeline, Depends(get_pipeline)]) -> dict[str, Any]:
    d = store.get_decision(valid_id(insight_id, "insight_id"))
    if d is None:
        raise not_found("decision")
    view = _decision_view(d)
    if d["decision"] == Outcome.NO_SURVEY.value:
        row = store.get_insight(insight_id)
        decision = pipeline.decide_one(row)
        doc = decision.to_no_survey_contract()
        view["no_survey"] = doc
        view["no_survey_schema_valid"] = not pipeline.registry.errors(SchemaName.NO_SURVEY, doc)
    return view


@router.get("/human-queue", tags=["decisions"], summary="Critical insights routed for a human call instead of a survey")
def human_queue(store: Annotated[Store, Depends(get_store)], limit: LimitQ = 50, offset: OffsetQ = 0) -> dict[str, Any]:
    return page_or_422(store.list_decisions, rule="R2", limit=limit, offset=offset)


# ---------- surveys / hand-offs ----------

@router.get("/surveys", tags=["surveys"])
def list_surveys(store: Annotated[Store, Depends(get_store)], limit: LimitQ = 50, offset: OffsetQ = 0, farmer_id: str | None = None,
                 status: str | None = None, language: str | None = None) -> dict[str, Any]:
    return page_or_422(store.list_surveys, farmer_id=farmer_id, status=status, language=valid_language(language), limit=limit, offset=offset)


@router.get("/surveys/{survey_id}", tags=["surveys"], summary="Survey document, validation report and optional channel rendering")
def get_survey(survey_id: str, store: Annotated[Store, Depends(get_store)],
               render: str | None = Query(None, pattern="^(bottom_sheet)$"), channel: str = Query("app", pattern="^(app|web)$")) -> dict[str, Any]:
    row = store.get_survey(valid_id(survey_id, "survey_id"))
    if row is None:
        raise not_found("survey")
    survey = json.loads(row["survey_json"]) if row["survey_json"] else None
    out = {"survey_id": row["survey_id"], "insight_id": row["insight_id"], "farmer_id": row["farmer_id"], "language": row["language"],
           "status": row["status"], "generation_source": row["generation_source"], "attempts": row["attempts"],
           "validation": json.loads(row["validation_json"]), "timing": json.loads(row["timing_json"]), "survey": survey}
    handoff = store.get_handoff_for_survey(survey_id)
    out["handoff_id"] = handoff["handoff_id"] if handoff else None
    if render == "bottom_sheet" and survey:
        out["bottom_sheet"] = render_bottom_sheet(survey, channel)
    return out


@router.get("/handoffs", tags=["scheduling"], summary="Scheduler hand-offs and their delivery state")
def list_handoffs(store: Annotated[Store, Depends(get_store)], limit: LimitQ = 50, offset: OffsetQ = 0, state: str | None = None,
                  farmer_id: str | None = None, priority: str | None = Query(None, pattern="^(high|normal|low)$")) -> dict[str, Any]:
    return page_or_422(store.list_handoffs, state=state, farmer_id=farmer_id, priority=priority, limit=limit, offset=offset)


@router.get("/handoffs/{handoff_id}", tags=["scheduling"])
def get_handoff(handoff_id: str, store: Annotated[Store, Depends(get_store)]) -> dict[str, Any]:
    row = store.get_handoff(valid_id(handoff_id, "handoff_id"))
    if row is None:
        raise not_found("handoff")
    return {k: row[k] for k in ("handoff_id", "survey_id", "farmer_id", "priority", "not_before", "not_after", "expires_at", "state", "state_detail", "counted_at", "updated_at")} | {
        "handoff": json.loads(row["handoff_json"]), "attempts": store.attempts_for_handoff(handoff_id)}


# ---------- deliveries / responses ----------

@router.get("/deliveries", tags=["delivery"], summary="Simulated delivery attempts")
def list_deliveries(store: Annotated[Store, Depends(get_store)], limit: LimitQ = 50, offset: OffsetQ = 0, state: str | None = None,
                    channel: str | None = Query(None, pattern="^(app|web|whatsapp|telegram|voice)$")) -> dict[str, Any]:
    return page_or_422(store.list_attempts, state=state, channel=channel, limit=limit, offset=offset)


@router.get("/responses", tags=["delivery"], summary="Simulated answer records")
def list_responses(store: Annotated[Store, Depends(get_store)], limit: LimitQ = 50, offset: OffsetQ = 0, survey_id: str | None = None,
                   status: str | None = None, needs_follow_up: bool | None = None) -> dict[str, Any]:
    return page_or_422(store.list_responses, survey_id=survey_id, status=status, needs_follow_up=needs_follow_up, limit=limit, offset=offset)


@router.get("/responses/{response_key}", tags=["delivery"])
def get_response(response_key: str, store: Annotated[Store, Depends(get_store)]) -> dict[str, Any]:
    row = store.get_response(valid_id(response_key, "response_key"))
    if row is None:
        raise not_found("response")
    return {"response_key": row["response_key"], "record": json.loads(row["record_json"])}


@router.get("/follow-up-queue", tags=["delivery"], summary="Answers that must go back to FarmerChat for follow-up")
def follow_up_queue(store: Annotated[Store, Depends(get_store)], limit: LimitQ = 50, offset: OffsetQ = 0) -> dict[str, Any]:
    return page_or_422(store.list_responses, needs_follow_up=True, limit=limit, offset=offset)


# ---------- stats / audit ----------

@router.get("/stats", tags=["stats"], summary="Ingestion, decision, survey, scheduling and delivery counters")
def stats(pipeline: Annotated[Pipeline, Depends(get_pipeline)]) -> dict[str, Any]:
    return pipeline.summary()


@router.get("/stats/ingestion", tags=["stats"])
def ingestion_stats(store: Annotated[Store, Depends(get_store)]) -> dict[str, Any]:
    run = store.latest_ingest_run()
    if run is None:
        raise HTTPException(404, "no ingestion run yet; POST /runs/ingest")
    return run


@router.get("/audit", tags=["stats"], summary="Append-only audit log")
def audit(store: Annotated[Store, Depends(get_store)], limit: LimitQ = 50, offset: OffsetQ = 0, entity: str | None = None,
          entity_id: str | None = None) -> dict[str, Any]:
    return page_or_422(store.list_audit, entity=entity, entity_id=entity_id, limit=limit, offset=offset)


@router.get("/budget", tags=["budget"], summary="Bedrock spending ledger status")
def budget(pipeline: Annotated[Pipeline, Depends(get_pipeline)]) -> dict[str, Any]:
    controller = getattr(pipeline, "budget", None)
    if controller is None:
        raise HTTPException(503, "budget controller not initialised")
    return controller.status().to_dict()
