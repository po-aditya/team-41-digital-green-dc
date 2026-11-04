"""Workflow-triggering endpoints. Operator token required. Safe defaults: offline, bounded, idempotent.

Only /runs/generate can ever reach Bedrock, and only when the request asks for
provider=bedrock with confirm_paid=true AND MEL_ALLOW_PAID_INFERENCE is enabled AND
the app was started with the Bedrock provider AND the budget controller has headroom.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from mel_agent.api.deps import get_pipeline, require_operator, valid_id, valid_ist, valid_language
from mel_agent.delivery.broadcaster import MAX_STEP_MINUTES, MIN_STEP_MINUTES
from mel_agent.evaluation.golden import evaluate_golden
from mel_agent.pipeline import IngestionIncomplete, Pipeline
from mel_agent.time_utils import format_ist

router = APIRouter(prefix="/runs", tags=["runs"], dependencies=[Depends(require_operator)])


def _now(pipeline: Pipeline) -> str:
    return format_ist(pipeline.clock.now)


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class IngestRequest(_Strict):
    now: str | None = Field(None, description="Ingestion timestamp (IST). Defaults to the simulated clock.")


@router.post("/ingest", summary="Ingest the participant pack (idempotent, free)")
def run_ingest(pipeline: Annotated[Pipeline, Depends(get_pipeline)], body: IngestRequest | None = Body(None)) -> dict[str, Any]:
    now = valid_ist(body.now if body else None, "now") or _now(pipeline)
    return pipeline.ingest(now).to_dict()


class DecideRequest(_Strict):
    limit: int | None = Field(None, ge=1, le=10000)


@router.post("/decide", summary="Run eligibility over ingested insights (free)")
def run_decide(pipeline: Annotated[Pipeline, Depends(get_pipeline)], body: DecideRequest | None = Body(None)) -> dict[str, Any]:
    try:
        return pipeline.decide_all(_now(pipeline), limit=body.limit if body else None)
    except IngestionIncomplete as exc:
        raise HTTPException(409, str(exc)) from None


class GenerateRequest(_Strict):
    limit: int = Field(25, ge=1, le=500, description="Bounded by default; raise deliberately for a full run.")
    language: str | None = Field(None, description="Override the farmer's conversation language (e.g. hi-IN).")
    insight_ids: list[str] | None = Field(None, max_length=200)
    provider: Literal["template", "bedrock"] = "template"
    confirm_paid: bool = Field(False, description="Must be true to run the paid Bedrock provider.")


@router.post("/generate", summary="Generate and schedule surveys for eligible insights")
def run_generate(pipeline: Annotated[Pipeline, Depends(get_pipeline)], body: GenerateRequest | None = Body(None)) -> dict[str, Any]:
    body = body or GenerateRequest()
    valid_language(body.language)
    for i in body.insight_ids or []:
        valid_id(i, "insight_id")
    if body.provider == "bedrock":
        if not pipeline.settings.allow_paid_inference:
            raise HTTPException(403, "paid inference is disabled (MEL_ALLOW_PAID_INFERENCE); use provider=template")
        if not body.confirm_paid:
            raise HTTPException(403, "paid inference requires confirm_paid=true")
        if pipeline.generator.provider.name != "bedrock":
            raise HTTPException(409, "the running pipeline was not started with the Bedrock provider (MEL_GENERATION_PROVIDER=bedrock)")
    elif pipeline.generator.provider.name != "template":
        raise HTTPException(409, "the running pipeline uses a non-template provider; restart with MEL_GENERATION_PROVIDER=template for free runs")
    try:
        stats = pipeline.generate_and_schedule(_now(pipeline), insight_ids=body.insight_ids, limit=body.limit, language=body.language)
    except IngestionIncomplete as exc:
        raise HTTPException(409, str(exc)) from None
    return stats.to_dict()


class ProcessRequest(_Strict):
    language: str | None = None


@router.post("/process/{insight_id}", summary="Decide → generate → schedule one insight (template provider)")
def run_process(insight_id: str, pipeline: Annotated[Pipeline, Depends(get_pipeline)], body: ProcessRequest | None = Body(None)) -> dict[str, Any]:
    if pipeline.generator.provider.name != "template":
        raise HTTPException(409, "single-insight processing is only offered with the template provider")
    try:
        out = pipeline.process_insight(valid_id(insight_id, "insight_id"), _now(pipeline), language=valid_language(body.language if body else None))
    except IngestionIncomplete as exc:
        raise HTTPException(409, str(exc)) from None
    if out.get("status") == "unknown_insight":
        raise HTTPException(404, "insight not found")
    return out


class BroadcastRequest(_Strict):
    until: str = Field(..., description="Advance the simulated clock to this IST time, ticking the broadcaster")
    step_minutes: int = Field(60, ge=MIN_STEP_MINUTES, le=MAX_STEP_MINUTES)


@router.post("/broadcast", summary="Advance the simulated clock and deliver due surveys to the simulated channels")
def run_broadcast(pipeline: Annotated[Pipeline, Depends(get_pipeline)], body: BroadcastRequest) -> dict[str, Any]:
    valid_ist(body.until, "until")
    try:
        return pipeline.run_broadcaster(body.until, body.step_minutes)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None


@router.get("/clock", summary="Simulated clock")
def get_clock(pipeline: Annotated[Pipeline, Depends(get_pipeline)]) -> dict[str, Any]:
    return {"now": format_ist(pipeline.clock.now)}


@router.post("/evaluate", summary="Evaluate the rules and template generator against the golden set (free)")
def run_evaluate(pipeline: Annotated[Pipeline, Depends(get_pipeline)], language: str = "en-IN") -> dict[str, Any]:
    valid_language(language)
    report = evaluate_golden(pipeline.paths, pipeline.rules, pipeline.calendar, pipeline.registry, pipeline.settings, language=language)
    return report.to_dict()
