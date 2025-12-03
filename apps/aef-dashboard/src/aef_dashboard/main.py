"""AEF Dashboard - FastAPI application."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

import uvicorn
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

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan manager."""
    logger.info("Starting AEF Dashboard...")
    yield
    logger.info("Shutting down AEF Dashboard...")


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
    async def health() -> dict[str, str]:
        """Health check endpoint."""
        return {"status": "healthy"}

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
