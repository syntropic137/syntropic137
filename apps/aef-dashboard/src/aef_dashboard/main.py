"""AEF Dashboard - FastAPI application."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

import uvicorn
from agentic_logging import get_logger, setup_logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from aef_dashboard.api import (
    artifacts_router,
    events_router,
    execution_router,
    metrics_router,
    sessions_router,
    workflows_router,
)
from aef_dashboard.config import get_dashboard_config
from aef_shared.settings import get_settings

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

# Initialize structured logging from agentic-primitives
# Configure via env vars: LOG_LEVEL, LOG_FORMAT (json/human), LOG_LEVEL_<COMPONENT>
setup_logging()
logger = get_logger(__name__)

# Global reference to subscription service for health checks
_subscription_service = None


def _validate_api_keys() -> None:
    """Validate required API keys are available at startup.

    Fail-fast behavior:
    - TEST: No API key required (mocks are used)
    - DEVELOPMENT: Warning only (allows read-only dashboard usage)
    - PRODUCTION/STAGING: Fail hard - workflow execution requires API key
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    settings = get_settings()

    if not api_key:
        if settings.is_test:
            logger.info("No ANTHROPIC_API_KEY set (test mode - using mocks)")
        elif settings.app_environment == "development":
            logger.warning(
                "⚠️  ANTHROPIC_API_KEY not set - workflow execution will fail. "
                "Set it in .env to enable real agent execution."
            )
        else:
            # Production/Staging - fail hard
            raise RuntimeError(
                f"ANTHROPIC_API_KEY is required in {settings.app_environment} mode. "
                "Workflow execution cannot proceed without it. "
                "Set the environment variable and restart."
            )
    else:
        # Mask key for logging (show first 8 chars)
        masked = api_key[:8] + "..." if len(api_key) > 8 else "***"
        logger.info("✓ ANTHROPIC_API_KEY configured (%s)", masked)


async def _start_subscription_service() -> None:
    """Start the event subscription service for projection updates.

    This connects to the event store and subscribes to events,
    dispatching them to projections in real-time.
    """
    global _subscription_service

    try:
        from aef_adapters.projection_stores import get_projection_store
        from aef_adapters.projections import get_projection_manager
        from aef_adapters.storage import (
            connect_event_store,
            get_event_store_client,
        )
        from aef_adapters.subscriptions import EventSubscriptionService
        from aef_shared.settings import get_settings

        settings = get_settings()

        # Skip subscription in test environment
        if settings.is_test:
            logger.info("Skipping subscription service in test environment")
            return

        # Connect to event store
        await connect_event_store()
        logger.info("Connected to event store")

        # Create and start subscription service
        _subscription_service = EventSubscriptionService(
            event_store_client=get_event_store_client(),
            projection_manager=get_projection_manager(),
            projection_store=get_projection_store(),
            batch_size=100,
            position_save_interval=10,
        )
        await _subscription_service.start()
        logger.info("Event subscription service started")

    except ImportError as e:
        logger.warning(
            "Could not start subscription service - missing dependencies: %s",
            e,
        )
    except Exception as e:
        logger.error(
            "Failed to start subscription service: %s",
            e,
            exc_info=True,
        )


async def _stop_subscription_service() -> None:
    """Stop the event subscription service gracefully."""
    global _subscription_service

    if _subscription_service is not None:
        try:
            await _subscription_service.stop()
            logger.info("Event subscription service stopped")
        except Exception as e:
            logger.error("Error stopping subscription service: %s", e)

    try:
        from aef_adapters.storage import disconnect_event_store

        await disconnect_event_store()
        logger.info("Disconnected from event store")
    except Exception as e:
        logger.warning("Error disconnecting from event store: %s", e)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan manager.

    On startup:
        - Validate API keys (fail-fast)
        - Connect to event store
        - Start subscription service for projection updates

    On shutdown:
        - Stop subscription service
        - Disconnect from event store
    """
    logger.info("Starting AEF Dashboard...")

    # Fail-fast: validate required API keys
    _validate_api_keys()

    # Start subscription service
    await _start_subscription_service()

    yield

    logger.info("Shutting down AEF Dashboard...")

    # Stop subscription service
    await _stop_subscription_service()


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
    app.include_router(sessions_router, prefix="/api")
    app.include_router(artifacts_router, prefix="/api")
    app.include_router(events_router, prefix="/api")
    app.include_router(metrics_router, prefix="/api")

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
        """Health check endpoint with subscription status."""
        response: dict = {"status": "healthy"}

        if _subscription_service is not None:
            response["subscription"] = {
                "running": _subscription_service.is_running,
                "caught_up": _subscription_service.is_caught_up,
                "last_position": _subscription_service.last_position,
                "events_processed": _subscription_service.events_processed,
            }

        return response

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
