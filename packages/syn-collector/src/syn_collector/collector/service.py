"""FastAPI service for receiving batched events.

Provides HTTP endpoints for sidecars to post events
with automatic deduplication.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

from fastapi import FastAPI

from syn_collector.collector.dedup import DeduplicationFilter
from syn_collector.events.types import BatchResponse, EventBatch

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
        if hasattr(store, "initialize"):
            await store.initialize()  # type: ignore[union-attr]
        yield
        logger.info("Event collector service stopping")
        if hasattr(store, "close"):
            await store.close()  # type: ignore[union-attr]

    application = FastAPI(
        title="Syn137 Event Collector",
        description="Scalable event collection for agent observability",
        version="0.1.0",
        lifespan=lifespan,
    )

    @application.post("/events", response_model=BatchResponse)
    async def receive_events(batch: EventBatch) -> BatchResponse:
        """Receive a batch of events from a sidecar.

        Events are deduplicated by event_id and written to
        the observability store.
        """
        accepted = 0
        duplicates = 0

        for event in batch.events:
            if dedup.is_duplicate(event.event_id):
                duplicates += 1
                continue

            try:
                await store.write_event(event)
                accepted += 1
            except Exception as e:
                logger.error(
                    f"Failed to write event: {e}",
                    extra={
                        "event_id": event.event_id,
                        "batch_id": batch.batch_id,
                        "error": str(e),
                    },
                )
                continue

        logger.info(
            f"Processed batch {batch.batch_id}: {accepted} accepted, {duplicates} duplicates",
            extra={
                "batch_id": batch.batch_id,
                "agent_id": batch.agent_id,
                "accepted": accepted,
                "duplicates": duplicates,
                "total": len(batch.events),
            },
        )

        return BatchResponse(
            accepted=accepted,
            duplicates=duplicates,
            batch_id=batch.batch_id,
        )

    @application.get("/health")
    async def health() -> dict[str, str]:
        """Health check endpoint."""
        return {"status": "healthy"}

    @application.get("/stats")
    async def stats() -> dict[str, Any]:
        """Get collector statistics."""
        return {
            "dedup": dedup.stats,
            "hit_rate": dedup.hit_rate(),
        }

    @application.post("/reset")
    async def reset() -> dict[str, str]:
        """Reset collector state (for testing)."""
        dedup.clear()
        return {"status": "reset"}

    return application
