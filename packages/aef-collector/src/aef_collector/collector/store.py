"""Event store writer for persisting events via gRPC.

Connects to the AEF Event Store service and writes
collected events as domain events.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from aef_collector.events.types import CollectedEvent

logger = logging.getLogger(__name__)


class EventStoreProtocol(Protocol):
    """Protocol for event store clients."""

    async def append(
        self,
        aggregate_id: str,
        aggregate_type: str,
        event_type: str,
        event_data: dict[str, Any],
        version: int,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Append an event to the store."""
        ...


class EventStoreWriter:
    """Write collected events to the event store.

    Translates CollectedEvent instances to the event store format
    and handles batch writes.

    Attributes:
        client: Event store client (gRPC or in-memory)
    """

    def __init__(
        self,
        client: EventStoreProtocol | None = None,
        *,
        aggregate_type: str = "AgentSession",
    ) -> None:
        """Initialize the event store writer.

        Args:
            client: Event store client (optional for testing)
            aggregate_type: Type name for events (default AgentSession)
        """
        self._client = client
        self._aggregate_type = aggregate_type
        self._version_cache: dict[str, int] = {}

    async def write(self, event: CollectedEvent) -> str | None:
        """Write a single event to the store.

        Args:
            event: CollectedEvent to persist

        Returns:
            Event ID from store, or None if no client
        """
        if self._client is None:
            logger.debug("No event store client configured, skipping write")
            return None

        # Get next version for this aggregate
        version = self._get_next_version(event.session_id)

        try:
            event_id = await self._client.append(
                aggregate_id=event.session_id,
                aggregate_type=self._aggregate_type,
                event_type=event.event_type.value,
                event_data=event.data,
                version=version,
                metadata={
                    "collector_event_id": event.event_id,
                    "collector_timestamp": event.timestamp.isoformat(),
                },
            )

            # Update version cache on success
            self._version_cache[event.session_id] = version

            return event_id

        except Exception as e:
            logger.error(
                f"Failed to write event to store: {e}",
                extra={
                    "event_id": event.event_id,
                    "session_id": event.session_id,
                    "error": str(e),
                },
            )
            raise

    async def write_batch(self, events: list[CollectedEvent]) -> list[str]:
        """Write multiple events to the store.

        Events are written sequentially to maintain ordering.

        Args:
            events: List of events to persist

        Returns:
            List of event IDs from store
        """
        event_ids: list[str] = []

        for event in events:
            event_id = await self.write(event)
            if event_id:
                event_ids.append(event_id)

        return event_ids

    def _get_next_version(self, session_id: str) -> int:
        """Get next version for an aggregate.

        Args:
            session_id: Aggregate identifier

        Returns:
            Next version number (starts at 1)
        """
        current = self._version_cache.get(session_id, 0)
        return current + 1

    def reset_version_cache(self) -> None:
        """Clear version cache (for testing)."""
        self._version_cache.clear()


class InMemoryEventStore:
    """In-memory event store for testing.

    Stores events in a list, useful for unit tests.
    """

    def __init__(self) -> None:
        """Initialize empty store."""
        self.events: list[dict[str, Any]] = []

    async def append(
        self,
        aggregate_id: str,
        aggregate_type: str,
        event_type: str,
        event_data: dict[str, Any],
        version: int,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Append event to in-memory list.

        Returns:
            Generated event ID
        """
        import uuid

        event_id = str(uuid.uuid4())

        self.events.append(
            {
                "event_id": event_id,
                "aggregate_id": aggregate_id,
                "aggregate_type": aggregate_type,
                "event_type": event_type,
                "event_data": event_data,
                "version": version,
                "metadata": metadata or {},
            }
        )

        return event_id

    def get_events(self, aggregate_id: str | None = None) -> list[dict[str, Any]]:
        """Get stored events, optionally filtered.

        Args:
            aggregate_id: Optional filter by aggregate

        Returns:
            List of stored events
        """
        if aggregate_id is None:
            return self.events.copy()

        return [e for e in self.events if e["aggregate_id"] == aggregate_id]

    def clear(self) -> None:
        """Clear all stored events."""
        self.events.clear()
