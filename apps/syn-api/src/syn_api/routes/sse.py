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
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from agentic_logging import get_logger
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

import syn_api.services.realtime as rt
from syn_api.types import Err

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from syn_adapters.projections.realtime import (
        JsonValue,
        RealTimeProjection,
        SSEEventFrame,
        SSEQueue,
    )

logger = get_logger(__name__)

router = APIRouter(tags=["sse"])

_ACTIVITY_CHANNEL = "_activity_"

_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",  # disable nginx buffering for streaming
}


# ---------------------------------------------------------------------------
# Shared SSE stream helpers
# ---------------------------------------------------------------------------

_KEEPALIVE = ": keepalive\n\n"


class _KeepAlive:
    """Typed sentinel returned by ``_next_frame`` on keepalive timeout."""


_KEEPALIVE_SENTINEL = _KeepAlive()


async def _next_frame(queue: SSEQueue) -> SSEEventFrame | None | _KeepAlive:
    """Read next frame, returning ``_KEEPALIVE_SENTINEL`` on timeout."""
    try:
        return await asyncio.wait_for(queue.get(), timeout=30.0)
    except TimeoutError:
        return _KEEPALIVE_SENTINEL


def _handshake_line(execution_id: str | None, data: dict[str, JsonValue]) -> str:
    """Build the initial ``connected`` SSE data line."""
    from syn_adapters.projections.realtime import SSEEventFrame as _Frame

    frame = _Frame(
        type="connected",
        event_type="connected",
        execution_id=execution_id,
        data=data,
        timestamp=datetime.now(UTC).isoformat(),
    )
    return f"data: {frame.model_dump_json()}\n\n"


async def _stream_frames(request: Request, queue: SSEQueue) -> AsyncGenerator[str, None]:
    """Yield SSE data lines from *queue* until disconnect or terminal sentinel."""
    while not await request.is_disconnected():
        result = await _next_frame(queue)
        if isinstance(result, _KeepAlive):
            yield _KEEPALIVE
        elif result is None:
            return
        else:
            yield f"data: {result.model_dump_json()}\n\n"


async def _sse_stream(
    *,
    request: Request,
    channel: str,
    queue: SSEQueue,
    realtime: RealTimeProjection,
    handshake_data: dict[str, JsonValue],
    execution_id: str | None,
) -> AsyncGenerator[str, None]:
    """Yield SSE frames: handshake, then forwarded domain events with keepalive."""
    try:
        yield _handshake_line(execution_id, handshake_data)
        async for line in _stream_frames(request, queue):
            yield line
    except Exception:
        logger.exception("SSE stream error", extra={"channel": channel})
    finally:
        with contextlib.suppress(Exception):
            await realtime.disconnect(channel, queue)


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
    stream = _sse_stream(
        request=request,
        channel=execution_id,
        queue=queue,
        realtime=realtime,
        handshake_data={},
        execution_id=execution_id,
    )
    return StreamingResponse(stream, media_type="text/event-stream", headers=_SSE_HEADERS)


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
    stream = _sse_stream(
        request=request,
        channel=_ACTIVITY_CHANNEL,
        queue=queue,
        realtime=realtime,
        handshake_data={"channel": "activity"},
        execution_id=None,
    )
    return StreamingResponse(stream, media_type="text/event-stream", headers=_SSE_HEADERS)


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
