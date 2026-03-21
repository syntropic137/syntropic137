"""Real-time projection that pushes events to SSE subscribers.

This projection doesn't persist data - it forwards events from the
subscription service to connected SSE clients in real-time.

This is the correct ES pattern: events flow through the event store,
subscription service dispatches to projections, and this projection
delivers events to the UI via Server-Sent Events.

Architecture:
    Event Store → Subscription Service → ProjectionManager
                                              │
                                              ▼
                                     RealTimeProjection
                                              │
                                              ▼
                                       SSE Clients
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Literal, TypeAlias

from agentic_logging import get_logger
from pydantic import BaseModel, ConfigDict

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

# Recursive JSON value type — justified: domain event payloads are
# arbitrary model_dump() outputs. JsonValue captures all serialisable
# leaf types; the recursive structure is validated by Pydantic at frame
# construction time.
type JsonValue = str | int | float | bool | None | list[JsonValue] | dict[str, JsonValue]

# Queue type alias — one queue per SSE subscriber.
# None is the sentinel that signals the stream should close (terminal event).
SSEQueue: TypeAlias = asyncio.Queue["SSEEventFrame | None"]


class SSEEventFrame(BaseModel):
    """Typed envelope for all SSE frames pushed to subscribers.

    Every frame sent over an SSE connection is serialised from this model.
    The ``type`` field distinguishes the three frame kinds:

    - ``connected``: initial handshake sent when a client subscribes
    - ``event``: a domain event forwarded from the event store
    - ``terminal``: signals the stream is ending (execution complete/failed)
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    type: Literal["connected", "event", "terminal"]
    event_type: str
    execution_id: str | None = None
    # Data is the domain event model_dump() output, constrained to JSON
    # via the JsonValue recursive type. The domain layer owns the schema;
    # Pydantic validates the recursive structure at frame construction.
    data: dict[str, JsonValue]
    timestamp: str


# ---------------------------------------------------------------------------
# Projection
# ---------------------------------------------------------------------------


class RealTimeProjection:
    """Projection that pushes domain events to SSE subscribers.

    This projection:
    1. Maintains a registry of asyncio queues per channel (execution_id or
       the global ``_activity_`` channel)
    2. Receives events from ProjectionManager (via subscription service)
    3. Broadcasts typed SSEEventFrame objects onto each subscriber's queue

    It does NOT persist any data — it's a pure forwarding layer.
    """

    # Projection interface
    name = "realtime"

    # Channel key used for the global activity feed
    _ACTIVITY_KEY = "_activity_"

    def __init__(self) -> None:
        """Initialise the real-time projection."""
        # channel → set of subscriber queues
        self._queues: dict[str, set[SSEQueue]] = {}
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    @property
    def connection_count(self) -> int:
        """Total number of active SSE subscribers."""
        return sum(len(qs) for qs in self._queues.values())

    @property
    def execution_count(self) -> int:
        """Number of channels with at least one active subscriber."""
        return len(self._queues)

    async def connect(self, channel: str) -> SSEQueue:
        """Register a new SSE subscriber for *channel*.

        Creates a fresh queue, adds it to the channel's subscriber set,
        and returns it.  The caller (route handler) owns the queue and
        must call :meth:`disconnect` in its ``finally`` block.

        Args:
            channel: Execution ID or ``_activity_`` for the global feed.

        Returns:
            The subscriber's dedicated queue.
        """
        queue: SSEQueue = asyncio.Queue()
        async with self._lock:
            if channel not in self._queues:
                self._queues[channel] = set()
            self._queues[channel].add(queue)

        logger.debug(
            "SSE client connected",
            extra={"channel": channel, "subscribers": len(self._queues.get(channel, set()))},
        )
        return queue

    async def disconnect(self, channel: str, queue: SSEQueue) -> None:
        """Unregister a subscriber queue for *channel*.

        Args:
            channel: The channel the subscriber was listening on.
            queue: The queue returned by :meth:`connect`.
        """
        async with self._lock:
            if channel in self._queues:
                self._queues[channel].discard(queue)
                if not self._queues[channel]:
                    del self._queues[channel]

        logger.debug("SSE client disconnected", extra={"channel": channel})

    # ------------------------------------------------------------------
    # Broadcasting
    # ------------------------------------------------------------------

    async def broadcast(
        self,
        channel: str,
        event_type: str,
        data: dict[str, JsonValue],
        *,
        terminal: bool = False,
    ) -> None:
        """Put a frame onto every subscriber queue for *channel*.

        Args:
            channel: Execution ID or ``_activity_``.
            event_type: Domain event type string (e.g. ``"PhaseStarted"``).
            data: Event payload from ``model_dump()``.
            terminal: If ``True``, also enqueue the ``None`` sentinel so
                route handlers exit cleanly after delivering the frame.
        """
        logger.info(
            "Broadcasting SSE event",
            extra={
                "channel": channel,
                "event_type": event_type,
                "subscribers": len(self._queues.get(channel, set())),
            },
        )

        frame = SSEEventFrame(
            type="terminal" if terminal else "event",
            event_type=event_type,
            execution_id=channel if channel != self._ACTIVITY_KEY else None,
            data=data,
            timestamp=datetime.now(UTC).isoformat(),
        )

        async with self._lock:
            queues = list(self._queues.get(channel, set()))

        for queue in queues:
            await queue.put(frame)
            if terminal:
                await queue.put(None)  # sentinel — closes the SSE stream

    async def broadcast_global(
        self,
        event_type: str,
        data: dict[str, JsonValue],
    ) -> None:
        """Broadcast a repo-level event to all global activity subscribers.

        Used for git commit/push events and other non-execution-scoped events
        that should appear in the dashboard's global live feed.

        Args:
            event_type: Event type string (e.g. ``"git_commit"``).
            data: Event payload.
        """
        await self.broadcast(self._ACTIVITY_KEY, event_type, data)

    # ------------------------------------------------------------------
    # Event handlers — called by ProjectionManager / RealTimeProjectionAdapter
    # ------------------------------------------------------------------

    async def on_workflow_execution_started(self, event: dict[str, JsonValue]) -> None:
        """Handle WorkflowExecutionStarted event."""
        execution_id = event.get("execution_id")
        if isinstance(execution_id, str):
            await self.broadcast(execution_id, "WorkflowExecutionStarted", event)

    async def on_phase_started(self, event: dict[str, JsonValue]) -> None:
        """Handle PhaseStarted event."""
        execution_id = event.get("execution_id")
        if isinstance(execution_id, str):
            await self.broadcast(execution_id, "PhaseStarted", event)

    async def on_phase_completed(self, event: dict[str, JsonValue]) -> None:
        """Handle PhaseCompleted event."""
        execution_id = event.get("execution_id")
        if isinstance(execution_id, str):
            await self.broadcast(execution_id, "PhaseCompleted", event)

    async def on_workflow_completed(self, event: dict[str, JsonValue]) -> None:
        """Handle WorkflowCompleted event — sends terminal sentinel."""
        execution_id = event.get("execution_id")
        if isinstance(execution_id, str):
            await self.broadcast(execution_id, "WorkflowCompleted", event, terminal=True)

    async def on_workflow_failed(self, event: dict[str, JsonValue]) -> None:
        """Handle WorkflowFailed event — sends terminal sentinel."""
        execution_id = event.get("execution_id")
        if isinstance(execution_id, str):
            await self.broadcast(execution_id, "WorkflowFailed", event, terminal=True)

    async def on_session_started(self, event: dict[str, JsonValue]) -> None:
        """Handle SessionStarted event."""
        execution_id = event.get("execution_id")
        if isinstance(execution_id, str):
            await self.broadcast(execution_id, "SessionStarted", event)

    async def on_session_completed(self, event: dict[str, JsonValue]) -> None:
        """Handle SessionCompleted event."""
        execution_id = event.get("execution_id")
        if isinstance(execution_id, str):
            await self.broadcast(execution_id, "SessionCompleted", event)

    async def on_operation_recorded(self, event: dict[str, JsonValue]) -> None:
        """Handle OperationRecorded event (tool calls, messages, etc.)."""
        execution_id = event.get("execution_id")
        if isinstance(execution_id, str):
            await self.broadcast(execution_id, "OperationRecorded", event)

    async def on_artifact_created(self, event: dict[str, JsonValue]) -> None:
        """Handle ArtifactCreated event."""
        execution_id = event.get("execution_id")
        if isinstance(execution_id, str):
            await self.broadcast(execution_id, "ArtifactCreated", event)

    async def on_subagent_started(self, event: dict[str, JsonValue]) -> None:
        """Handle SubagentStarted event — subagent spawned via Task tool."""
        execution_id = event.get("execution_id")
        if isinstance(execution_id, str):
            await self.broadcast(execution_id, "SubagentStarted", event)

    async def on_subagent_stopped(self, event: dict[str, JsonValue]) -> None:
        """Handle SubagentStopped event — subagent completed."""
        execution_id = event.get("execution_id")
        if isinstance(execution_id, str):
            await self.broadcast(execution_id, "SubagentStopped", event)


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_realtime_projection: RealTimeProjection | None = None


def get_realtime_projection() -> RealTimeProjection:
    """Return the singleton RealTimeProjection instance."""
    global _realtime_projection
    if _realtime_projection is None:
        _realtime_projection = RealTimeProjection()
    return _realtime_projection


def reset_realtime_projection() -> None:
    """Reset the singleton (for testing)."""
    global _realtime_projection
    _realtime_projection = None
