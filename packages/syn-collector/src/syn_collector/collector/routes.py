"""Route handlers for the event collector service.

Extracted from service.py to keep create_app() under LOC limits.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from syn_collector.events.types import BatchResponse, EventBatch

if TYPE_CHECKING:
    from fastapi import FastAPI

    from syn_collector.collector.dedup import DeduplicationFilter
    from syn_collector.collector.store import ObservabilityStoreProtocol

logger = logging.getLogger(__name__)


def register_routes(
    app: FastAPI,
    store: ObservabilityStoreProtocol,
    dedup: DeduplicationFilter,
) -> None:
    """Register all route handlers on the FastAPI application.

    Args:
        app: FastAPI application instance
        store: Observability event store
        dedup: Deduplication filter
    """

    @app.post("/events", response_model=BatchResponse)
    async def receive_events(batch: EventBatch) -> BatchResponse:
        """Receive a batch of events from a sidecar."""
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

    @app.get("/health")
    async def health() -> dict[str, str]:
        """Health check endpoint."""
        return {"status": "healthy"}

    @app.get("/stats")
    async def stats() -> dict[str, Any]:
        """Get collector statistics."""
        return {
            "dedup": dedup.stats,
            "hit_rate": dedup.hit_rate(),
        }

    @app.post("/reset")
    async def reset() -> dict[str, str]:
        """Reset collector state (for testing)."""
        dedup.clear()
        return {"status": "reset"}
