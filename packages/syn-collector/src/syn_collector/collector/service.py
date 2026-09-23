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
from syn_collector.collector.version import version_string

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
        # The INSTALLED release, not a literal. Hardcoded "0.1.0" here was the
        # same defect #1380 fixed in syn-api, on the sibling service: it named
        # a build that had not been current for twenty-odd releases, and the
        # collector is deployed and scraped exactly like the API is.
        #
        # OpenAPI requires info.version to be a non-empty string, so this one
        # slot cannot report "no metadata" the way /health does (null, plus an
        # explicit version_status). It says "unknown" instead - deliberately
        # not a version number, so it cannot be mistaken for the release it is
        # standing in for. See syn_collector.collector.version.UNKNOWN_VERSION.
        version=version_string(),
        lifespan=lifespan,
    )

    register_routes(application, store, dedup)

    return application
