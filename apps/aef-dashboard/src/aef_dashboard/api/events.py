"""Events API endpoint with Server-Sent Events (SSE)."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

from fastapi import APIRouter, Query
from sse_starlette.sse import EventSourceResponse

router = APIRouter(prefix="/events", tags=["events"])


# In-memory event buffer for SSE subscribers
# In production, this would use Redis pub/sub or similar
_event_buffer: list[dict[str, Any]] = []
_max_buffer_size = 1000


def push_event(event_type: str, data: dict[str, Any]) -> None:
    """Push an event to the buffer for SSE subscribers.

    This is called by the workflow execution engine to notify
    dashboard subscribers of workflow progress.
    """
    global _event_buffer
    event = {
        "event_type": event_type,
        "timestamp": datetime.now(UTC).isoformat(),
        "data": data,
    }
    _event_buffer.append(event)

    # Keep buffer size bounded
    if len(_event_buffer) > _max_buffer_size:
        _event_buffer = _event_buffer[-_max_buffer_size:]


def get_recent_events(limit: int = 50, workflow_id: str | None = None) -> list[dict[str, Any]]:
    """Get recent events from the buffer."""
    events = _event_buffer[-limit:]

    if workflow_id:
        events = [e for e in events if e.get("data", {}).get("workflow_id") == workflow_id]

    return events


async def event_generator(
    workflow_id: str | None = None,
    last_event_id: int = 0,
) -> AsyncGenerator[dict[str, str], None]:
    """Generate SSE events for subscribers.

    Args:
        workflow_id: Optional filter by workflow ID.
        last_event_id: Resume from this event index.

    Yields:
        SSE event dictionaries with 'event', 'data', and 'id' keys.
    """
    event_index = last_event_id

    # Send initial connection event
    yield {
        "event": "connected",
        "data": json.dumps(
            {
                "message": "Connected to event stream",
                "workflow_filter": workflow_id,
                "timestamp": datetime.now(UTC).isoformat(),
            }
        ),
        "id": str(event_index),
    }

    # Send any buffered events since last_event_id
    for i, event in enumerate(_event_buffer[last_event_id:], start=last_event_id):
        if workflow_id and event.get("data", {}).get("workflow_id") != workflow_id:
            continue

        event_index = i + 1
        yield {
            "event": event["event_type"],
            "data": json.dumps(event["data"]),
            "id": str(event_index),
        }

    # Keep connection alive and send new events
    last_buffer_size = len(_event_buffer)

    while True:
        await asyncio.sleep(0.5)  # Check for new events every 500ms

        current_buffer_size = len(_event_buffer)
        if current_buffer_size > last_buffer_size:
            # New events available
            for event in _event_buffer[last_buffer_size:]:
                if workflow_id and event.get("data", {}).get("workflow_id") != workflow_id:
                    continue

                event_index += 1
                yield {
                    "event": event["event_type"],
                    "data": json.dumps(event["data"]),
                    "id": str(event_index),
                }

            last_buffer_size = current_buffer_size

        # Send periodic heartbeat to keep connection alive
        yield {
            "event": "heartbeat",
            "data": json.dumps({"timestamp": datetime.now(UTC).isoformat()}),
            "id": str(event_index),
        }


@router.get("/stream")
async def stream_events(
    workflow_id: str | None = Query(None, description="Filter events by workflow ID"),
    last_event_id: int = Query(0, ge=0, description="Resume from event ID"),
) -> EventSourceResponse:
    """Stream real-time workflow events via Server-Sent Events (SSE).

    Connect to this endpoint with an EventSource client to receive
    real-time updates about workflow execution progress.

    Events include:
    - workflow_started: Workflow execution began
    - phase_started: A phase began execution
    - phase_completed: A phase finished (success or failure)
    - workflow_completed: Workflow finished successfully
    - workflow_failed: Workflow failed with error
    - heartbeat: Periodic keep-alive signal

    Example JavaScript client:
    ```javascript
    const evtSource = new EventSource('/api/events/stream?workflow_id=xxx');
    evtSource.onmessage = (event) => console.log(event.data);
    evtSource.addEventListener('phase_completed', (e) => console.log(e.data));
    ```
    """
    return EventSourceResponse(
        event_generator(workflow_id=workflow_id, last_event_id=last_event_id),
        media_type="text/event-stream",
    )


@router.get("/recent", response_model=list[dict[str, Any]])
async def get_recent(
    workflow_id: str | None = Query(None, description="Filter events by workflow ID"),
    limit: int = Query(50, ge=1, le=200, description="Max events to return"),
) -> list[dict[str, Any]]:
    """Get recent events from the buffer.

    Use this for initial page load before connecting to SSE stream.
    """
    return get_recent_events(limit=limit, workflow_id=workflow_id)


@router.post("/push")
async def push_event_endpoint(
    event_type: str = Query(..., description="Event type"),
    workflow_id: str | None = Query(None, description="Workflow ID"),
    phase_id: str | None = Query(None, description="Phase ID"),
    session_id: str | None = Query(None, description="Session ID"),
) -> dict[str, str]:
    """Push a custom event (for testing/debugging).

    In production, events are pushed by the workflow execution engine.
    """
    data = {
        "workflow_id": workflow_id,
        "phase_id": phase_id,
        "session_id": session_id,
    }
    push_event(event_type, data)
    return {"status": "ok", "event_type": event_type}


def clear_events() -> None:
    """Clear all events from the buffer (for testing)."""
    global _event_buffer
    _event_buffer = []
