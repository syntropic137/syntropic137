"""FastAPI service for receiving batched events.

Provides HTTP endpoints for sidecars to post events
with automatic deduplication.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from fastapi import FastAPI

from syn_collector.collector.dedup import DeduplicationFilter
from syn_collector.collector.routes import register_routes

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from syn_collector.collector.store import ObservabilityStoreProtocol

logger = logging.getLogger(__name__)


def create_app(
    store: ObservabilityStoreProtocol,
    dedup_max_size: int = 100_000,
) -> FastAPI:
    """Create configured FastAPI application.

    Args:
        store: Observability event store (required — no silent fallback)
        dedup_max_size: Max size for dedup cache

    Returns:
        Configured FastAPI application with all routes
    """
    dedup = DeduplicationFilter(max_size=dedup_max_size)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        """Application lifespan handler."""
        logger.info("Event collector service starting")
        _init = getattr(store, "initialize", None)
        if _init is not None:
            await _init()
        yield
        logger.info("Event collector service stopping")
        _close = getattr(store, "close", None)
        if _close is not None:
            await _close()

    application = FastAPI(
        title="Syn137 Event Collector",
        description="Scalable event collection for agent observability",
        version="0.1.0",
        lifespan=lifespan,
    )

    register_routes(application, store, dedup)

    return application
