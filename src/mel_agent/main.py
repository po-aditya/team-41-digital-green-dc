"""FastAPI entry point. Run with: uvicorn mel_agent.main:app"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from mel_agent import __version__
from mel_agent.config import Settings, get_settings
from mel_agent.contracts import SchemaRegistry

logger = logging.getLogger("mel_agent")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        logging.basicConfig(level=settings.log_level)
        # Fail fast if the contracts cannot load: nothing downstream is safe without them.
        app.state.schemas = SchemaRegistry(settings.schemas_dir)
        logger.info("Loaded %d schemas from %s", len(app.state.schemas.schemas), settings.schemas_dir)
        yield

    app = FastAPI(title="FarmerChat MEL Survey Agent", version=__version__, lifespan=lifespan)
    app.state.settings = settings

    @app.get("/healthz")
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
            },
        }

    return app


app = create_app()
