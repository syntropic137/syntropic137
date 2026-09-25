"""Syntropic137 API — FastAPI application."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

import uvicorn
from agentic_logging import get_logger, setup_logging
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from syn_api.build_info import get_build_info, version_string
from syn_api.config import get_api_config
from syn_api.routes import (
    artifacts_router,
    capture_router,
    claude_plugins_router,
    conversations_router,
    costs_router,
    events_router,
    executions_router,
    features_router,
    github_router,
    insights_router,
    maintenance_router,
    metrics_router,
    observability_router,
    organizations_router,
    repos_router,
    sessions_router,
    skills_router,
    sse_router,
    systems_router,
    triggers_router,
    webhooks_router,
    workflows_router,
)
from syn_api.strict_query import reject_unknown_query_params
from syn_api.types import Err, FeatureDisabledResponse, HealthResponse, Ok, RootResponse

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
    import syn_api.services.lifecycle as lifecycle

    logger.info("Starting Syntropic137 API...")

    result = await lifecycle.startup()
    if isinstance(result, Err):
        logger.error("Startup failed: %s — refusing to serve traffic", result.message)
        raise RuntimeError(f"Startup aborted: {result.message}")

    logger.info("Startup complete (mode=%s)", result.value.get("mode", "full"))

    yield

    logger.info("Shutting down Syntropic137 API...")
    await lifecycle.shutdown()


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    config = get_api_config()

    app = FastAPI(
        title="Syntropic137 API",
        description=(
            "API for Syntropic137. "
            "Provides real-time observability for workflow execution, "
            "agent sessions, and artifacts."
        ),
        # The INSTALLED release, not a literal. This was hardcoded "0.5.1" and
        # had drifted twenty releases behind the package it describes, so
        # openapi.json — and every CLI type and doc page generated from it —
        # named a build that was not running (#1380).
        #
        # THE ONE PLACE A SENTINEL IS UNAVOIDABLE, and the only remaining
        # caller of version_string(). The OpenAPI specification requires
        # info.version to be a non-empty string: the field has no null and no
        # neighbouring field to name a state with, so unlike /health's build
        # block and the root response — both of which report a null release
        # plus an explicit version_status — this slot has to put SOMETHING
        # here. It says "unknown", deliberately a word and not a version
        # number, so nothing downstream can parse or compare it as a release
        # the way it could a fabricated "0.0.0". See
        # syn_api.build_info.UNKNOWN_VERSION. Do not copy this pattern to a
        # field that could have been nullable.
        version=version_string(),
        lifespan=lifespan,
        debug=config.debug,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        # Refuse a query parameter no route declares, everywhere, once (#1313).
        # A global dependency is the only registration point that also covers
        # routes added later - see syn_api.strict_query for why neither
        # middleware nor a route_class can be applied in one place here.
        dependencies=[Depends(reject_unknown_query_params)],
    )

    # Add CORS middleware for frontend dev server
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Per-route request-timing (Lane 2 observability - see #1070). Always on:
    # in-process only, no event store or aggregate interaction, negligible cost.
    from syn_api.middleware.request_timing import RequestTimingMiddleware

    app.add_middleware(RequestTimingMiddleware)

    # Webhook recording middleware (opt-in via SYN_RECORD_WEBHOOKS=true)
    import os

    if os.environ.get("SYN_RECORD_WEBHOOKS", "").lower() == "true":
        from syn_api.middleware.webhook_recorder import WebhookRecorderMiddleware

        app.add_middleware(WebhookRecorderMiddleware)
        logger.info("Webhook recording enabled — saving to fixtures/webhooks/")

    # ── API routers ────────────────────────────────────────────────────
    # No prefix here — versioning is handled at the routing layer (nginx).
    # nginx: location /api/v1/ → proxy_pass http://api:8000/
    # So /api/v1/workflows → strips to /workflows → matches these routes.
    app.include_router(workflows_router)
    app.include_router(executions_router)
    app.include_router(sessions_router)
    app.include_router(artifacts_router)
    app.include_router(claude_plugins_router)
    app.include_router(skills_router)
    app.include_router(metrics_router)
    app.include_router(capture_router)
    app.include_router(observability_router)
    app.include_router(costs_router)
    app.include_router(events_router)
    app.include_router(github_router)
    app.include_router(conversations_router)
    app.include_router(triggers_router)
    app.include_router(webhooks_router)
    app.include_router(sse_router)
    app.include_router(organizations_router)
    app.include_router(systems_router)
    app.include_router(repos_router)
    app.include_router(insights_router)
    app.include_router(maintenance_router)
    app.include_router(features_router)

    # ── UI feedback (ADR-016, #105) ────────────────────────────────────
    # The standard API install stays independent of the feedback package.
    # Images built with the feedback extra keep stable routes across flag changes.
    from importlib.util import find_spec

    from syn_shared.settings.config import get_settings

    feedback_installed = find_spec("ui_feedback") is not None
    if get_settings().syn_ui_feedback_enabled and not feedback_installed:
        raise RuntimeError("UI feedback is enabled; install syn-api[feedback]")
    if feedback_installed:
        from ui_feedback.router import create_feedback_router

        from syn_api.services import ui_feedback as ui_feedback_service

        feedback_router, feedback_overrides = create_feedback_router(
            ui_feedback_service.get_feedback_storage,
            max_upload_bytes=ui_feedback_service.MAX_UPLOAD_BYTES,
        )
        app.dependency_overrides.update(feedback_overrides)
        app.include_router(
            feedback_router,
            responses={404: {"model": FeatureDisabledResponse}},
        )

    @app.get("/")
    async def root() -> RootResponse:
        """Root endpoint with API info.

        Reports a null release and ``version_status: "unavailable"`` rather than
        the ``"unknown"`` sentinel it used to serve. It was a flat map of
        strings, so it had nowhere to put a null and nothing to name the state
        with — which made it the last surface still answering "which build?"
        with a literal, the thing #1380 exists to remove (see ``RootResponse``).
        """
        return RootResponse(
            name="Syntropic137 API",
            version=get_build_info().version,
            docs="/docs",
            health="/health",
        )

    @app.get("/health")
    async def health() -> HealthResponse:
        """Health check endpoint with detailed subscription status."""
        import syn_api.services.lifecycle as lifecycle

        result = await lifecycle.health_check()
        if isinstance(result, Ok):
            return result.value
        # An unhealthy process still has to say which build is unhealthy: that
        # answer is read from package metadata and needs none of the state that
        # just failed.
        return HealthResponse(status="unhealthy", mode="degraded", build=get_build_info())

    return app


# Create app instance for uvicorn
app = create_app()


def run() -> None:
    """Run the API server."""
    config = get_api_config()
    logger.info("Starting Syntropic137 API on %s:%d", config.host, config.port)
    uvicorn.run(
        "syn_api.main:app",
        host=config.host,
        port=config.port,
        reload=config.debug,
    )


if __name__ == "__main__":
    run()
