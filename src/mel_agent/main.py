"""FastAPI entry point. Run with: uvicorn mel_agent.main:app"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from mel_agent import __version__
from mel_agent.config import Settings, get_settings
from mel_agent.contracts import SchemaRegistry

logger = logging.getLogger("mel_agent")


def build_pipeline(settings: Settings, registry: SchemaRegistry):
    """Wire store, budget controller, provider and pipeline. Bedrock only when explicitly configured."""
    from mel_agent.budget import BudgetController
    from mel_agent.llm.pricing import PricingConfigError, PricingTable
    from mel_agent.pipeline import Pipeline
    from mel_agent.store import Store

    store = Store.from_url(settings.database_url)
    try:
        pricing = PricingTable.load(settings.pricing_file)
    except PricingConfigError as exc:
        logger.warning("pricing unavailable (%s); paid inference will be refused", exc)
        pricing = None
    budget = BudgetController(store, settings, pricing)
    provider = None
    if settings.generation_provider == "bedrock":
        from mel_agent.generation.providers import BedrockProvider
        from mel_agent.llm.bedrock import BedrockInvoker
        from mel_agent.llm.budgeted import BudgetedInvoker

        provider = BedrockProvider(BudgetedInvoker(BedrockInvoker(settings, pricing=pricing), budget), max_tokens=settings.bedrock_max_tokens)
    pipeline = Pipeline(settings, store, registry, provider=provider)
    pipeline.budget = budget  # type: ignore[attr-defined]
    return store, pipeline, budget


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        logging.basicConfig(level=settings.log_level)
        # Fail fast if the contracts cannot load: nothing downstream is safe without them.
        app.state.schemas = SchemaRegistry(settings.schemas_dir)
        logger.info("Loaded %d schemas from %s", len(app.state.schemas.schemas), settings.schemas_dir)
        store, pipeline, budget = build_pipeline(settings, app.state.schemas)
        app.state.store, app.state.pipeline, app.state.budget = store, pipeline, budget
        yield

    app = FastAPI(
        title="FarmerChat MEL Survey Agent", version=__version__, lifespan=lifespan,
        description="Reads FarmerChat insights, decides which deserve a follow-up survey, writes tap-answer surveys, "
                    "hands them to a scheduler and simulates delivery. All runs are offline unless the Bedrock provider is explicitly enabled.",
    )
    app.state.settings = settings

    @app.get("/healthz", tags=["health"])
    def healthz() -> dict:
        # Liveness only: no AWS calls, so it works without credentials.
        registry = getattr(app.state, "schemas", None)
        return {
            "status": "ok",
            "version": __version__,
            "env": settings.app_env,
            "schemas_loaded": sorted(n.value for n in registry.schemas) if registry else [],
            "bedrock": {
                "region": settings.resolved_bedrock_region,
                "model_id": settings.bedrock_model_id,
                "paid_inference_enabled": settings.allow_paid_inference,
                "generation_provider": settings.generation_provider,
            },
        }

    from fastapi.exceptions import RequestValidationError
    from fastapi.responses import JSONResponse

    from mel_agent.api.read import router as read_router
    from mel_agent.api.runs import router as runs_router

    import re as _re

    _SAFE_LOC = _re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,40}$")

    def _safe_loc(parts, error_type: str) -> list[str]:
        """Locations name our own fields or indexes. Caller-supplied names (unknown fields) are never echoed."""
        out = []
        for p in parts:
            if isinstance(p, int):
                out.append(str(p))
            elif error_type == "extra_forbidden" and p == parts[-1]:
                out.append("<unknown field>")
            elif isinstance(p, str) and _SAFE_LOC.match(p):
                out.append(p)
            else:
                out.append("<redacted>")
        return out

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request, exc: RequestValidationError):
        # Field locations and fixed messages only: never echo submitted values or caller-chosen names.
        errors = [{"loc": _safe_loc(list(e.get("loc", [])), str(e.get("type", ""))), "msg": str(e.get("msg", "invalid"))[:200], "type": str(e.get("type", ""))[:60]}
                  for e in exc.errors()]
        return JSONResponse(status_code=422, content={"detail": errors})

    @app.exception_handler(Exception)
    async def _unhandled(request, exc: Exception):
        logger.error("unhandled %s on %s", type(exc).__name__, request.url.path)
        return JSONResponse(status_code=500, content={"detail": "internal error"})

    app.include_router(read_router)
    app.include_router(runs_router)
    return app


app = create_app()
