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
    control_router,
    conversations_router,
    costs_router,
    events_router,
    execution_router,
    executions_router,
    metrics_router,
    observability_router,
    sessions_router,
    webhooks_router,
    websocket_router,
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

    Also exports the API key to os.environ so that agent adapters
    (which read from os.environ) can access it.
    """
    settings = get_settings()
    api_key = settings.anthropic_api_key

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
        # Export to os.environ so agent adapters can find it
        # (ClaudeAgenticAgent reads from os.environ.get("ANTHROPIC_API_KEY"))
        key_value = api_key.get_secret_value()
        os.environ["ANTHROPIC_API_KEY"] = key_value

        # Mask key for logging (show first 8 chars)
        masked = key_value[:8] + "..." if len(key_value) > 8 else "***"
        logger.info("✓ ANTHROPIC_API_KEY configured and exported (%s)", masked)


def _validate_github_app() -> None:
    """Validate GitHub App is configured at startup.

    Poka-Yoke: Fail fast if GitHub App credentials are missing.
    GitHub App is REQUIRED for:
    - Creating PRs from agent workflows
    - Git authentication in isolated containers
    - Secure, auditable GitHub operations

    This prevents silent failures when running workflows that need GitHub.
    """
    from aef_shared.settings.github import GitHubAppSettings

    settings = get_settings()
    github = GitHubAppSettings()

    if not github.is_configured:
        missing = []
        if not github.app_id:
            missing.append("AEF_GITHUB_APP_ID")
        if not github.private_key.get_secret_value():
            missing.append("AEF_GITHUB_PRIVATE_KEY")
        if not github.installation_id:
            missing.append("AEF_GITHUB_INSTALLATION_ID")

        missing_str = ", ".join(missing)

        if settings.is_test:
            logger.info("GitHub App not configured (test mode - mocks will be used)")
        elif settings.app_environment == "development":
            # In development, fail hard - we need GitHub for PR workflows
            raise RuntimeError(
                f"GitHub App is REQUIRED but not configured. "
                f"Missing: {missing_str}. "
                f"Ensure .env is loaded with GitHub App credentials. "
                f"See docs/deployment/github-app-setup.md for setup instructions."
            )
        else:
            # Production/Staging - definitely fail
            raise RuntimeError(
                f"GitHub App is REQUIRED in {settings.app_environment} mode. "
                f"Missing: {missing_str}. "
                f"Set these environment variables and restart."
            )
    else:
        logger.info(
            "✓ GitHub App configured (app_id=%s, bot=%s)",
            github.app_id,
            github.bot_name,
        )


async def _start_subscription_service() -> None:
    """Start the coordinator subscription service for projection updates.

    This connects to the event store and subscribes to events,
    dispatching them to projections in real-time using the new
    SubscriptionCoordinator architecture (ADR-014).
    """
    global _subscription_service

    try:
        from aef_adapters.projection_stores import get_projection_store
        from aef_adapters.projections.realtime import get_realtime_projection
        from aef_adapters.storage import (
            connect_event_store,
            get_event_store_client,
        )
        from aef_adapters.subscriptions import create_coordinator_service
        from aef_shared.settings import get_settings

        settings = get_settings()

        # Skip subscription in test environment
        if settings.is_test:
            logger.info("Skipping subscription service in test environment")
            return

        # Initialize AgentEventStore for TimescaleDB queries (ADR-029)
        try:
            from aef_adapters.events import get_event_store

            event_store = get_event_store()
            await event_store.initialize()
            logger.info("AgentEventStore initialized for event queries")
        except Exception as e:
            logger.warning(
                "Could not initialize AgentEventStore, event data may be unavailable: %s", e
            )

        # Connect to event store
        await connect_event_store()
        logger.info("Connected to event store")

        # Create and start coordinator subscription service (ADR-014)
        _subscription_service = create_coordinator_service(
            event_store=get_event_store_client(),
            projection_store=get_projection_store(),
            realtime_projection=get_realtime_projection(),
        )
        await _subscription_service.start()
        logger.info("Coordinator subscription service started (ADR-014)")

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
        - Validate GitHub App (fail-fast)
        - Connect to event store
        - Start subscription service for projection updates

    On shutdown:
        - Stop subscription service
        - Disconnect from event store
    """
    logger.info("Starting AEF Dashboard...")

    # Fail-fast: validate required credentials (Poka-Yoke)
    _validate_api_keys()
    _validate_github_app()

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
    app.include_router(executions_router, prefix="/api")  # Execution detail
    app.include_router(sessions_router, prefix="/api")
    app.include_router(artifacts_router, prefix="/api")
    app.include_router(metrics_router, prefix="/api")
    app.include_router(observability_router, prefix="/api")  # Tool/token metrics
    app.include_router(control_router, prefix="/api")  # Execution control (pause/resume/cancel)
    app.include_router(costs_router, prefix="/api")  # Cost tracking
    app.include_router(events_router, prefix="/api")  # Raw event queries (ADR-029)
    app.include_router(conversations_router, prefix="/api")  # Conversation logs (ADR-035)

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
        response: dict = {"status": "healthy"}

        if _subscription_service is not None:
            # Use the new detailed status method
            response["subscription"] = _subscription_service.get_status()

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
