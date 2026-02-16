"""AEF Dashboard - FastAPI application."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

import uvicorn
from agentic_logging import get_logger, setup_logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from aef_api.types import Ok
from aef_dashboard.api import (
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
from aef_dashboard.config import get_dashboard_config

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
    import aef_api.v1.lifecycle as lifecycle

    logger.info("Starting AEF Dashboard...")

    result = await lifecycle.startup()
    if hasattr(result, "value"):
        logger.info("Startup complete")
    else:
        msg = getattr(result, "message", "unknown error")
        logger.error("Startup failed: %s", msg)

    yield

    logger.info("Shutting down AEF Dashboard...")
    await lifecycle.shutdown()


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    config = get_dashboard_config()

    app = FastAPI(
        title="AEF Dashboard API",
        description=(
            "Dashboard API for Agentic Engineering Framework. "
            "Provides real-time observability for workflow execution, "
            "agent sessions, and artifacts."
        ),
        version="0.1.0",
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

    # Register API routers
    app.include_router(workflows_router, prefix="/api")
    app.include_router(execution_router, prefix="/api")  # Workflow execution
    app.include_router(executions_router, prefix="/api")  # Execution detail
    app.include_router(sessions_router, prefix="/api")
    app.include_router(artifacts_router, prefix="/api")
    app.include_router(metrics_router, prefix="/api")
    app.include_router(observability_router, prefix="/api")  # Tool/token metrics
    app.include_router(control_router, prefix="/api")  # Execution control (pause/resume/cancel)
    app.include_router(costs_router, prefix="/api")  # Cost tracking
    app.include_router(events_router, prefix="/api")  # Raw event queries (ADR-029)
    app.include_router(conversations_router, prefix="/api")  # Conversation logs (ADR-035)
    app.include_router(triggers_router, prefix="/api")  # Trigger rules (self-healing)

    # Webhooks (no /api prefix - must match GitHub's webhook URL exactly)
    app.include_router(webhooks_router)

    # WebSocket endpoint for real-time events (no /api prefix)
    app.include_router(websocket_router)

    @app.get("/")
    async def root() -> dict[str, str]:
        """Root endpoint with API info."""
        return {
            "name": "AEF Dashboard API",
            "version": "0.1.0",
            "docs": "/docs",
            "health": "/health",
        }

    @app.get("/health")
    async def health() -> dict:
        """Health check endpoint with detailed subscription status."""
        import aef_api.v1.lifecycle as lifecycle

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
    logger.info("Starting AEF Dashboard on %s:%d", config.host, config.port)
    uvicorn.run(
        "aef_dashboard.main:app",
        host=config.host,
        port=config.port,
        reload=config.debug,
    )


if __name__ == "__main__":
    run()
