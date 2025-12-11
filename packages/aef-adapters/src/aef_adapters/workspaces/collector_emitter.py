"""Collector-compatible event emitter for workspace events.

Emits workspace events through the aef-collector service for
persistent storage and real-time observability.

Usage:
    from aef_adapters.workspaces import configure_workspace_emitter
    from aef_adapters.workspaces.collector_emitter import CollectorEmitter

    # Configure to send events to collector
    emitter = CollectorEmitter(collector_url="http://localhost:8080")
    configure_workspace_emitter(emitter=emitter, enabled=True)

    # Now all workspace operations will emit events to collector
    async with router.create(config) as workspace:
        ...  # Events automatically sent
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from aiohttp import ClientSession

logger = logging.getLogger(__name__)


def _generate_event_id(event_type: str, data: dict[str, Any]) -> str:
    """Generate deterministic event ID for deduplication.

    Uses SHA256 hash of event type + key fields to ensure
    the same event always produces the same ID.
    """
    # Key fields for deduplication
    key_parts = [
        event_type,
        data.get("workspace_id", ""),
        data.get("session_id", ""),
        str(data.get("started_at") or data.get("created_at") or data.get("executed_at", "")),
    ]
    content = ":".join(key_parts)
    return hashlib.sha256(content.encode()).hexdigest()[:32]


def _map_event_type(event_type: str) -> str:
    """Map domain event type to collector event type.

    Domain events: WorkspaceCreating, WorkspaceCreated, etc.
    Collector types: workspace_creating, workspace_created, etc.
    """
    mapping = {
        "WorkspaceCreating": "workspace_creating",
        "WorkspaceCreated": "workspace_created",
        "WorkspaceCommandExecuted": "workspace_command_executed",
        "WorkspaceDestroying": "workspace_destroying",
        "WorkspaceDestroyed": "workspace_destroyed",
        "WorkspaceError": "workspace_error",
    }
    return mapping.get(event_type, event_type.lower())


class CollectorEmitter:
    """Emits workspace events to the aef-collector service.

    Events are sent via HTTP POST to the collector's batch endpoint.
    Supports batching for efficiency and retry on failure.

    Attributes:
        collector_url: Base URL of the collector service
        agent_id: Identifier for this agent/service
        batch_size: Number of events before flushing (default: 1 for real-time)
    """

    def __init__(
        self,
        collector_url: str = "http://localhost:8080",
        agent_id: str | None = None,
        batch_size: int = 1,
    ) -> None:
        """Initialize collector emitter.

        Args:
            collector_url: Base URL of collector service
            agent_id: Unique agent identifier (auto-generated if not provided)
            batch_size: Events to batch before sending (1 = immediate)
        """
        self.collector_url = collector_url.rstrip("/")
        self.agent_id = agent_id or f"workspace-{uuid.uuid4().hex[:8]}"
        self.batch_size = batch_size
        self._batch: list[dict[str, Any]] = []
        self._session: ClientSession | None = None

    async def _get_session(self) -> ClientSession:
        """Get or create aiohttp session."""
        if self._session is None or self._session.closed:
            import aiohttp

            self._session = aiohttp.ClientSession()
        return self._session

    async def emit(self, event_type: str, data: dict[str, Any]) -> None:
        """Emit an event to the collector.

        Args:
            event_type: Type of event (e.g., "WorkspaceCreated")
            data: Event payload
        """
        # Build collector event
        event = {
            "event_id": _generate_event_id(event_type, data),
            "event_type": _map_event_type(event_type),
            "session_id": data.get("session_id", "unknown"),
            "timestamp": data.get("started_at")
            or data.get("created_at")
            or data.get("executed_at")
            or data.get("destroyed_at")
            or data.get("occurred_at")
            or datetime.now(UTC).isoformat(),
            "data": data,
        }

        self._batch.append(event)

        # Flush if batch is full
        if len(self._batch) >= self.batch_size:
            await self.flush()

    async def flush(self) -> None:
        """Send batched events to collector."""
        if not self._batch:
            return

        batch_id = f"batch-{uuid.uuid4().hex[:8]}"
        payload = {
            "agent_id": self.agent_id,
            "batch_id": batch_id,
            "events": self._batch,
        }

        try:
            session = await self._get_session()
            async with session.post(
                f"{self.collector_url}/events/batch",
                json=payload,
                timeout=10,
            ) as response:
                if response.status == 200:
                    result = await response.json()
                    logger.debug(
                        f"Collector accepted {result.get('accepted', 0)} events, "
                        f"{result.get('duplicates', 0)} duplicates"
                    )
                else:
                    logger.warning(f"Collector returned {response.status}: {await response.text()}")
        except Exception as e:
            logger.warning(f"Failed to send events to collector: {e}")
        finally:
            self._batch = []

    async def close(self) -> None:
        """Close the HTTP session."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None


class InMemoryCollectorEmitter:
    """In-memory emitter that stores events for testing/inspection.

    Useful for:
    - Testing that events are emitted correctly
    - Inspecting events in a single session
    - Demos without running collector service

    Usage:
        emitter = InMemoryCollectorEmitter()
        configure_workspace_emitter(emitter=emitter)

        # ... run workspace operations ...

        # Inspect collected events
        for event in emitter.events:
            print(event)
    """

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    async def emit(self, event_type: str, data: dict[str, Any]) -> None:
        """Store event in memory."""
        self.events.append(
            {
                "event_id": _generate_event_id(event_type, data),
                "event_type": event_type,
                "timestamp": datetime.now(UTC).isoformat(),
                "data": data,
            }
        )

    def clear(self) -> None:
        """Clear stored events."""
        self.events = []

    def get_by_type(self, event_type: str) -> list[dict[str, Any]]:
        """Get events of a specific type."""
        return [e for e in self.events if e["event_type"] == event_type]

    def get_by_session(self, session_id: str) -> list[dict[str, Any]]:
        """Get events for a specific session."""
        return [e for e in self.events if e["data"].get("session_id") == session_id]

    def get_by_workspace(self, workspace_id: str) -> list[dict[str, Any]]:
        """Get events for a specific workspace."""
        return [e for e in self.events if e["data"].get("workspace_id") == workspace_id]

    def summary(self) -> dict[str, Any]:
        """Get summary of collected events."""
        by_type: dict[str, int] = {}
        for event in self.events:
            event_type = event["event_type"]
            by_type[event_type] = by_type.get(event_type, 0) + 1

        return {
            "total_events": len(self.events),
            "by_type": by_type,
            "sessions": list({e["data"].get("session_id") for e in self.events}),
            "workspaces": list({e["data"].get("workspace_id") for e in self.events}),
        }
