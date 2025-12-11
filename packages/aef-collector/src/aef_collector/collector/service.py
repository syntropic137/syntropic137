"""FastAPI service for receiving batched events.

Provides HTTP endpoints for sidecars to post events
with automatic deduplication.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

from fastapi import FastAPI

from aef_collector.collector.dedup import DeduplicationFilter
from aef_collector.collector.store import EventStoreWriter, InMemoryEventStore
from aef_collector.events.types import BatchResponse, EventBatch

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

logger = logging.getLogger(__name__)


def create_app(
    event_store: Any | None = None,
    dedup_max_size: int = 100_000,
) -> FastAPI:
    """Create configured FastAPI application.

    Args:
        event_store: Event store client (optional)
        dedup_max_size: Max size for dedup cache

    Returns:
        Configured FastAPI application with all routes
    """
    # Configure dependencies
    dedup = DeduplicationFilter(max_size=dedup_max_size)

    if event_store is None:
        # Use in-memory store for development
        event_store = InMemoryEventStore()

    writer = EventStoreWriter(client=event_store)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        """Application lifespan handler."""
        logger.info("Event collector service starting")
        yield
        logger.info("Event collector service stopping")

    # Create the application
    application = FastAPI(
        title="AEF Event Collector",
        description="Scalable event collection for agent observability",
        version="0.1.0",
        lifespan=lifespan,
    )

    # Register routes with closure over dependencies
    @application.post("/events", response_model=BatchResponse)
    async def receive_events(batch: EventBatch) -> BatchResponse:
        """Receive a batch of events from a sidecar.

        Events are deduplicated by event_id and written to
        the event store.

        Args:
            batch: EventBatch containing events to process

        Returns:
            BatchResponse with counts of accepted/duplicates
        """
        accepted = 0
        duplicates = 0

        for event in batch.events:
            if dedup.is_duplicate(event.event_id):
                duplicates += 1
                continue

            try:
                await writer.write(event)
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
                # Continue processing other events
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
        """Health check endpoint.

        Returns:
            Status dict
        """
        return {"status": "healthy"}

    @application.get("/stats")
    async def stats() -> dict[str, Any]:
        """Get collector statistics.

        Returns:
            Deduplication and processing stats
        """
        return {
            "dedup": dedup.stats,
            "hit_rate": dedup.hit_rate(),
        }

    @application.post("/reset")
    async def reset() -> dict[str, str]:
        """Reset collector state (for testing).

        Returns:
            Status message
        """
        dedup.clear()
        writer.reset_version_cache()
        return {"status": "reset"}

    return application


# Default app instance for CLI usage
app = create_app()
