"""Syntropic137 Dashboard - FastAPI application."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

import uvicorn
from agentic_logging import get_logger, setup_logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from syn_api.types import Err, Ok
from syn_dashboard import __version__
from syn_dashboard.api import (
    artifacts_router,
    control_router,
    conversations_router,
    costs_router,
    events_router,
    execution_router,
    executions_router,
    metrics_router,
    observability_router,
    sessions_router,
    triggers_router,
    webhooks_router,
    websocket_router,
    workflows_router,
)
from syn_dashboard.config import get_dashboard_config

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

# Initialize structured logging from agentic-primitives
# Configure via env vars: LOG_LEVEL, LOG_FORMAT (json/human), LOG_LEVEL_<COMPONENT>
setup_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan manager.

    On startup:
        - Validate credentials (fail-fast)
        - Connect to event store
        - Start subscription service for projection updates

    On shutdown:
        - Stop subscription service
        - Disconnect from event store
    """
    import syn_api.v1.lifecycle as lifecycle

    logger.info("Starting Syntropic137 Dashboard...")

    result = await lifecycle.startup()
    if isinstance(result, Err):
        logger.error("Startup failed: %s — refusing to serve traffic", result.message)
        raise RuntimeError(f"Startup aborted: {result.message}")

    logger.info("Startup complete (mode=%s)", result.value.get("mode", "full"))

    yield

    logger.info("Shutting down Syntropic137 Dashboard...")
    await lifecycle.shutdown()


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    config = get_dashboard_config()

    app = FastAPI(
        title="Syntropic137 Dashboard API",
        description=(
            "Dashboard API for Syntropic137. "
            "Provides real-time observability for workflow execution, "
            "agent sessions, and artifacts."
        ),
        version=__version__,
        lifespan=lifespan,
        debug=config.debug,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    # Add CORS middleware for frontend dev server
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Webhook recording middleware (opt-in via SYN_RECORD_WEBHOOKS=true)
    import os

    if os.environ.get("SYN_RECORD_WEBHOOKS", "").lower() == "true":
        from syn_dashboard.middleware.webhook_recorder import WebhookRecorderMiddleware

        app.add_middleware(WebhookRecorderMiddleware)
        logger.info("Webhook recording enabled — saving to fixtures/webhooks/")

    # ── API routers ────────────────────────────────────────────────────
    # No prefix here — versioning is handled at the routing layer (nginx).
    # nginx: location /api/v1/ → proxy_pass http://dashboard:8000/
    # So /api/v1/workflows → strips to /workflows → matches these routes.
    app.include_router(workflows_router)
    app.include_router(execution_router)
    app.include_router(executions_router)
    app.include_router(sessions_router)
    app.include_router(artifacts_router)
    app.include_router(metrics_router)
    app.include_router(observability_router)
    app.include_router(control_router)
    app.include_router(costs_router)
    app.include_router(events_router)
    app.include_router(conversations_router)
    app.include_router(triggers_router)
    app.include_router(webhooks_router)
    app.include_router(websocket_router)

    @app.get("/")
    async def root() -> dict[str, str]:
        """Root endpoint with API info."""
        return {
            "name": "Syntropic137 Dashboard API",
            "version": __version__,
            "docs": "/docs",
            "health": "/health",
        }

    @app.get("/health")
    async def health() -> dict:
        """Health check endpoint with detailed subscription status."""
        import syn_api.v1.lifecycle as lifecycle

        result = await lifecycle.health_check()
        if isinstance(result, Ok):
            return result.value
        return {"status": "unhealthy"}

    return app


# Create app instance for uvicorn
app = create_app()


def run() -> None:
    """Run the dashboard server."""
    config = get_dashboard_config()
    logger.info("Starting Syntropic137 Dashboard on %s:%d", config.host, config.port)
    uvicorn.run(
        "syn_dashboard.main:app",
        host=config.host,
        port=config.port,
        reload=config.debug,
    )


if __name__ == "__main__":
    run()
