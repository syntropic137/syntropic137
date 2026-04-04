"""Route handlers for the event collector service.

Extracted from service.py to keep create_app() under LOC limits.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from fastapi import Request
from fastapi.responses import JSONResponse

from syn_collector.collector.otlp import parse_otlp_logs, parse_otlp_metrics
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

    # =========================================================================
    # OTLP Endpoints — OTel JSON ingestion from workspace containers
    # =========================================================================

    @app.post("/v1/metrics")
    async def otlp_metrics(request: Request) -> JSONResponse:
        """Receive OTLP JSON metrics from workspace containers.

        Parses Claude Code's OTel metrics (token usage, cost) and routes
        them through the existing observability pipeline.
        """
        try:
            payload = await request.json()
        except Exception:
            return JSONResponse(
                status_code=400,
                content={"error": "Invalid JSON payload"},
            )

        events = parse_otlp_metrics(payload)
        accepted = 0
        for event in events:
            if not dedup.is_duplicate(event.event_id):
                await store.write_event(event)
                accepted += 1

        logger.info("OTLP metrics: %d extracted, %d accepted", len(events), accepted)
        return JSONResponse(content={"accepted": accepted})

    @app.post("/v1/logs")
    async def otlp_logs(request: Request) -> JSONResponse:
        """Receive OTLP JSON logs from workspace containers."""
        try:
            payload = await request.json()
        except Exception:
            return JSONResponse(
                status_code=400,
                content={"error": "Invalid JSON payload"},
            )

        events = parse_otlp_logs(payload)
        accepted = 0
        for event in events:
            if not dedup.is_duplicate(event.event_id):
                await store.write_event(event)
                accepted += 1

        logger.info("OTLP logs: %d extracted, %d accepted", len(events), accepted)
        return JSONResponse(content={"accepted": accepted})
