"""Real-time projection that pushes events to WebSocket clients.

This projection doesn't persist data - it forwards events from the
subscription service to connected WebSocket clients in real-time.

This is the correct ES pattern: events flow through the event store,
subscription service dispatches to projections, and this projection
delivers events to the UI via WebSocket.

Architecture:
    Event Store → Subscription Service → ProjectionManager
                                              │
                                              ▼
                                     RealTimeProjection
                                              │
                                              ▼
                                     WebSocket Clients
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from weakref import WeakSet

from agentic_logging import get_logger

if TYPE_CHECKING:
    from fastapi import WebSocket

logger = get_logger(__name__)


class RealTimeProjection:
    """Projection that pushes domain events to WebSocket clients.

    This projection:
    1. Maintains a registry of WebSocket connections per execution_id
    2. Receives events from ProjectionManager (via subscription service)
    3. Broadcasts relevant events to connected clients

    It does NOT persist any data - it's a pure forwarding layer.
    """

    # Projection interface
    name = "realtime"

    def __init__(self) -> None:
        """Initialize the real-time projection."""
        # execution_id -> set of WebSocket connections
        self._connections: dict[str, WeakSet[WebSocket]] = {}
        self._lock = asyncio.Lock()

    @property
    def connection_count(self) -> int:
        """Get total number of active connections."""
        return sum(len(conns) for conns in self._connections.values())

    @property
    def execution_count(self) -> int:
        """Get number of executions with active connections."""
        return len(self._connections)

    async def connect(self, execution_id: str, websocket: WebSocket) -> None:
        """Register a WebSocket connection for an execution.

        Args:
            execution_id: The execution to subscribe to.
            websocket: The WebSocket connection.
        """
        async with self._lock:
            if execution_id not in self._connections:
                self._connections[execution_id] = WeakSet()
            self._connections[execution_id].add(websocket)

        logger.debug(
            "WebSocket connected for real-time events",
            extra={"execution_id": execution_id},
        )

    async def disconnect(self, execution_id: str, websocket: WebSocket) -> None:
        """Unregister a WebSocket connection.

        Args:
            execution_id: The execution subscribed to.
            websocket: The WebSocket connection.
        """
        async with self._lock:
            if execution_id in self._connections:
                self._connections[execution_id].discard(websocket)
                # Clean up empty sets
                if not self._connections[execution_id]:
                    del self._connections[execution_id]

        logger.debug(
            "WebSocket disconnected",
            extra={"execution_id": execution_id},
        )

    async def broadcast(
        self,
        execution_id: str,
        event_type: str,
        data: dict[str, Any],
    ) -> None:
        """Broadcast an event to all connected clients for an execution.

        Args:
            execution_id: The execution ID.
            event_type: The domain event type.
            data: The event data.
        """
        logger.info(
            "Broadcasting event to WebSocket clients",
            extra={
                "execution_id": execution_id,
                "event_type": event_type,
                "connection_count": len(self._connections.get(execution_id, [])),
            },
        )

        async with self._lock:
            connections = list(self._connections.get(execution_id, []))

        if not connections:
            return

        message = json.dumps(
            {
                "type": "event",
                "event_type": event_type,
                "data": data,
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )

        # Send to all connections, tracking dead ones
        dead_connections: list[WebSocket] = []
        for ws in connections:
            try:
                await ws.send_text(message)
            except Exception:
                dead_connections.append(ws)

        # Clean up dead connections
        if dead_connections:
            async with self._lock:
                for ws in dead_connections:
                    if execution_id in self._connections:
                        self._connections[execution_id].discard(ws)

    # ==========================================================================
    # Event Handlers - Called by ProjectionManager
    # ==========================================================================

    async def on_workflow_execution_started(self, event: dict[str, Any]) -> None:
        """Handle WorkflowExecutionStarted event."""
        execution_id = event.get("execution_id")
        if execution_id:
            await self.broadcast(execution_id, "WorkflowExecutionStarted", event)

    async def on_phase_started(self, event: dict[str, Any]) -> None:
        """Handle PhaseStarted event."""
        execution_id = event.get("execution_id")
        if execution_id:
            await self.broadcast(execution_id, "PhaseStarted", event)

    async def on_phase_completed(self, event: dict[str, Any]) -> None:
        """Handle PhaseCompleted event."""
        execution_id = event.get("execution_id")
        if execution_id:
            await self.broadcast(execution_id, "PhaseCompleted", event)

    async def on_workflow_completed(self, event: dict[str, Any]) -> None:
        """Handle WorkflowCompleted event."""
        execution_id = event.get("execution_id")
        if execution_id:
            await self.broadcast(execution_id, "WorkflowCompleted", event)

    async def on_workflow_failed(self, event: dict[str, Any]) -> None:
        """Handle WorkflowFailed event."""
        execution_id = event.get("execution_id")
        if execution_id:
            await self.broadcast(execution_id, "WorkflowFailed", event)

    async def on_session_started(self, event: dict[str, Any]) -> None:
        """Handle SessionStarted event."""
        execution_id = event.get("execution_id")
        if execution_id:
            await self.broadcast(execution_id, "SessionStarted", event)

    async def on_session_completed(self, event: dict[str, Any]) -> None:
        """Handle SessionCompleted event."""
        execution_id = event.get("execution_id")
        if execution_id:
            await self.broadcast(execution_id, "SessionCompleted", event)

    async def on_operation_recorded(self, event: dict[str, Any]) -> None:
        """Handle OperationRecorded event (tool calls, messages, etc.)."""
        execution_id = event.get("execution_id")
        if execution_id:
            await self.broadcast(execution_id, "OperationRecorded", event)

    async def on_artifact_created(self, event: dict[str, Any]) -> None:
        """Handle ArtifactCreated event."""
        # Artifacts may not have execution_id, but we can try
        execution_id = event.get("execution_id")
        if execution_id:
            await self.broadcast(execution_id, "ArtifactCreated", event)

    async def on_subagent_started(self, event: dict[str, Any]) -> None:
        """Handle SubagentStarted event - subagent spawned via Task tool."""
        execution_id = event.get("execution_id")
        if execution_id:
            await self.broadcast(execution_id, "SubagentStarted", event)

    async def on_subagent_stopped(self, event: dict[str, Any]) -> None:
        """Handle SubagentStopped event - subagent completed."""
        execution_id = event.get("execution_id")
        if execution_id:
            await self.broadcast(execution_id, "SubagentStopped", event)

    # ==========================================================================
    # Global Activity Channel
    # ==========================================================================

    _ACTIVITY_KEY = "_activity_"

    async def broadcast_global(self, event_type: str, data: dict[str, Any]) -> None:
        """Broadcast a repo-level event to all global activity feed subscribers.

        Used for git commit/push events and other non-execution-scoped events
        that should appear in the dashboard's global live feed.

        Args:
            event_type: The event type string (e.g. "git_commit").
            data: The event payload.
        """
        await self.broadcast(self._ACTIVITY_KEY, event_type, data)


# Singleton instance - registered with ProjectionManager at startup
_realtime_projection: RealTimeProjection | None = None


def get_realtime_projection() -> RealTimeProjection:
    """Get the singleton RealTimeProjection instance."""
    global _realtime_projection
    if _realtime_projection is None:
        _realtime_projection = RealTimeProjection()
    return _realtime_projection


def reset_realtime_projection() -> None:
    """Reset the singleton (for testing)."""
    global _realtime_projection
    _realtime_projection = None
