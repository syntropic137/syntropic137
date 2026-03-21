"""Server-Sent Events endpoints for real-time execution and activity streams.

Replaces the previous WebSocket endpoints with plain HTTP streaming.
Both streams are strictly server-to-client, making SSE the correct fit:

- ``GET /sse/executions/{execution_id}`` — domain events for one execution
- ``GET /sse/activity``                  — global git/activity feed
- ``GET /sse/health``                    — SSE subsystem health check

Wire format (text/event-stream):
    data: <SSEEventFrame JSON>\\n\\n        — domain event or connected handshake
    : keepalive\\n\\n                        — 30-second heartbeat (no-data comment)

Clients identify event types from the ``event_type`` field inside the JSON
payload.  No ``event:`` header line is emitted so ``EventSource.onmessage``
handles all frames uniformly.

Lifecycle:
    1. Client connects → route calls ``realtime.connect(channel)`` → queue returned
    2. Route sends ``connected`` handshake frame
    3. Loop: ``asyncio.wait_for(queue.get(), 30s)``
       - timeout  → emit keepalive comment
       - ``None`` sentinel → terminal event delivered; break
       - frame    → serialise with ``model_dump_json()`` and emit
    4. Client disconnects (``request.is_disconnected()``) → break
    5. ``finally`` → ``realtime.disconnect(channel, queue)``
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from agentic_logging import get_logger
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

import syn_api.v1.realtime as rt
from syn_api.types import Err

if TYPE_CHECKING:
    from syn_adapters.projections.realtime import SSEEventFrame, SSEQueue

logger = get_logger(__name__)

router = APIRouter(tags=["sse"])

_ACTIVITY_CHANNEL = "_activity_"

_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",  # disable nginx buffering for streaming
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _data_line(frame: SSEEventFrame) -> str:
    """Render *frame* as a single SSE ``data:`` line (terminated by \\n\\n)."""
    return f"data: {frame.model_dump_json()}\n\n"


# ---------------------------------------------------------------------------
# Execution stream
# ---------------------------------------------------------------------------


@router.get("/sse/executions/{execution_id}")
async def execution_sse(execution_id: str, request: Request) -> StreamingResponse:
    """Stream domain events for a single execution.

    Sends a ``connected`` handshake frame on connect, then forwards every
    domain event emitted by the RealTimeProjection for this execution.
    Closes automatically when a terminal event (WorkflowCompleted /
    WorkflowFailed) is broadcast, or when the client disconnects.
    """
    realtime = rt.get_realtime_projection_ref()
    queue: SSEQueue = await realtime.connect(execution_id)

    async def generate() -> AsyncGenerator[str, None]:
        try:
            from syn_adapters.projections.realtime import SSEEventFrame as _Frame

            connected = _Frame(
                type="connected",
                event_type="connected",
                execution_id=execution_id,
                data={},
                timestamp=datetime.now(UTC).isoformat(),
            )
            yield _data_line(connected)

            while True:
                if await request.is_disconnected():
                    logger.debug(
                        "SSE client disconnected", extra={"execution_id": execution_id}
                    )
                    break

                try:
                    frame: SSEEventFrame | None = await asyncio.wait_for(
                        queue.get(), timeout=30.0
                    )
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
                    continue

                if frame is None:
                    # Terminal sentinel — stream ends after last real frame
                    # was already delivered before the sentinel was enqueued.
                    break

                yield _data_line(frame)

        except Exception:
            logger.exception(
                "SSE stream error", extra={"execution_id": execution_id}
            )
        finally:
            with contextlib.suppress(Exception):
                await realtime.disconnect(execution_id, queue)

    return StreamingResponse(generate(), media_type="text/event-stream", headers=_SSE_HEADERS)


# ---------------------------------------------------------------------------
# Global activity feed
# ---------------------------------------------------------------------------


@router.get("/sse/activity")
async def activity_sse(request: Request) -> StreamingResponse:
    """Stream the global activity feed (git events, system-wide activity).

    Runs indefinitely until the client disconnects.  There is no terminal
    sentinel for the activity channel — it never completes.
    """
    realtime = rt.get_realtime_projection_ref()
    queue: SSEQueue = await realtime.connect(_ACTIVITY_CHANNEL)

    async def generate() -> AsyncGenerator[str, None]:
        try:
            from syn_adapters.projections.realtime import SSEEventFrame as _Frame

            connected = _Frame(
                type="connected",
                event_type="connected",
                execution_id=None,
                data={"channel": "activity"},
                timestamp=datetime.now(UTC).isoformat(),
            )
            yield _data_line(connected)

            while True:
                if await request.is_disconnected():
                    break

                try:
                    frame: SSEEventFrame | None = await asyncio.wait_for(
                        queue.get(), timeout=30.0
                    )
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
                    continue

                if frame is None:
                    break

                yield _data_line(frame)

        except Exception:
            logger.exception("SSE activity stream error")
        finally:
            with contextlib.suppress(Exception):
                await realtime.disconnect(_ACTIVITY_CHANNEL, queue)

    return StreamingResponse(generate(), media_type="text/event-stream", headers=_SSE_HEADERS)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


@router.get("/sse/health")
async def sse_health() -> dict[str, Any]:
    """Health check for the SSE subsystem.

    Returns active subscriber and execution counts from the RealTimeProjection.
    """
    result = await rt.get_realtime_health()

    if isinstance(result, Err):
        return {"status": "unhealthy"}

    health = result.value
    return {
        "status": "healthy",
        "active_executions": health.active_executions,
        "active_connections": health.active_connections,
    }
