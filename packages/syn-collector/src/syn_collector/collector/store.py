"""Observability store for persisting collected events.

Routes events to TimescaleDB via syn-adapters (AgentEventStore + EventBuffer).
Replaces the original gRPC-based EventStoreProtocol which used domain event
store concepts (aggregate_id, version) that are wrong for observability data.

See: ADR-026 (observability → TimescaleDB), ADR-013 (no in-memory in production)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from syn_collector.events.types import CollectedEvent

logger = logging.getLogger(__name__)


@runtime_checkable
class ObservabilityStoreProtocol(Protocol):
    """Protocol for observability event storage."""

    async def write_event(self, event: CollectedEvent) -> None:
        """Write a single event to the store."""
        ...

    async def write_batch(self, events: list[CollectedEvent]) -> None:
        """Write multiple events to the store."""
        ...


def _event_to_dict(event: CollectedEvent) -> dict[str, Any]:
    """Map a CollectedEvent to the dict shape AgentEvent.from_dict() expects.

    AgentEvent.from_dict() looks for:
    - "event_type" or "type" → EventType
    - "timestamp" or "time" → datetime
    - "session_id" → str
    - remaining keys → data payload
    """
    return {
        "event_type": event.event_type.value,
        "session_id": event.session_id,
        "timestamp": event.timestamp.isoformat(),
        **event.data,
    }


class TimescaleDBObservabilityStore:
    """Observability store backed by TimescaleDB via AgentEventStore + EventBuffer.

    Creates its own EventBuffer instance (not the singleton) to avoid
    coupling to the dashboard's buffer lifecycle.
    """

    def __init__(self, db_url: str) -> None:
        self._db_url = db_url
        self._store: Any = None  # AgentEventStore, set in initialize()
        self._buffer: Any = None  # EventBuffer, set in initialize()

    async def initialize(self) -> None:
        """Create store and buffer, connect to DB."""
        from syn_adapters.events.buffer import EventBuffer
        from syn_adapters.events.store import AgentEventStore

        self._store = AgentEventStore(self._db_url)
        await self._store.initialize()

        self._buffer = EventBuffer(self._store)
        await self._buffer.start()

        logger.info("TimescaleDB observability store initialized")

    async def write_event(self, event: CollectedEvent) -> None:
        """Write a single event via the buffer."""
        if self._buffer is None:
            msg = "Store not initialized — call initialize() first"
            raise RuntimeError(msg)
        await self._buffer.add(_event_to_dict(event))

    async def write_batch(self, events: list[CollectedEvent]) -> None:
        """Write multiple events via the buffer."""
        if self._buffer is None:
            msg = "Store not initialized — call initialize() first"
            raise RuntimeError(msg)
        await self._buffer.add_many([_event_to_dict(e) for e in events])

    async def close(self) -> None:
        """Flush remaining events and close connections."""
        if self._buffer is not None:
            await self._buffer.stop()
        if self._store is not None:
            await self._store.close()
        logger.info("TimescaleDB observability store closed")


class InMemoryObservabilityStore:
    """In-memory observability store for TESTING ONLY.

    Raises InMemoryStorageError if used outside test/offline environments.
    """

    def __init__(self) -> None:
        from syn_adapters.storage.in_memory import _assert_test_environment

        _assert_test_environment()
        self.events: list[dict[str, Any]] = []

    async def write_event(self, event: CollectedEvent) -> None:
        """Store event dict in memory."""
        self.events.append(_event_to_dict(event))

    async def write_batch(self, events: list[CollectedEvent]) -> None:
        """Store multiple event dicts in memory."""
        self.events.extend(_event_to_dict(e) for e in events)

    def clear(self) -> None:
        """Clear all stored events."""
        self.events.clear()
