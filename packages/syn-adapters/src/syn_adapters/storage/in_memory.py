"""In-memory storage utilities for TESTING ONLY.

Contains InMemoryEventStore, InMemoryEventPublisher and singleton factory
functions. All repositories now go through the SDK's EventStoreRepository
backed by MemoryEventStoreClient -- see repositories.py.

WARNING: These utilities are for unit/integration tests only.
See ADR-060 (docs/adrs/ADR-060-restart-safe-trigger-deduplication.md).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from syn_adapters.in_memory import InMemoryAdapter, InMemoryAdapterError, assert_test_only

if TYPE_CHECKING:
    from event_sourcing import EventEnvelope

# Re-export for backwards compatibility with existing imports
InMemoryStorageError = InMemoryAdapterError


@dataclass
class StoredEvent:
    """Represents a stored event in the in-memory store."""

    aggregate_id: str
    aggregate_type: str
    event_type: str
    event_data: dict[str, Any]
    version: int
    sequence: int


@dataclass
class InMemoryEventStore:
    """In-memory event store for TESTING ONLY.

    Raises:
        InMemoryStorageError: If instantiated outside test environment.
    """

    _events: list[StoredEvent] = field(default_factory=list)
    _sequence: int = field(default=0)

    def __post_init__(self) -> None:
        """Validate environment on initialization."""
        assert_test_only()

    def append(
        self,
        aggregate_id: str,
        aggregate_type: str,
        event_type: str,
        event_data: dict[str, Any],
        version: int,
    ) -> None:
        """Append an event to the store."""
        self._sequence += 1
        stored_event = StoredEvent(
            aggregate_id=aggregate_id,
            aggregate_type=aggregate_type,
            event_type=event_type,
            event_data=event_data,
            version=version,
            sequence=self._sequence,
        )
        self._events.append(stored_event)

    def get_events(self, aggregate_id: str) -> list[StoredEvent]:
        """Get all events for an aggregate."""
        return [e for e in self._events if e.aggregate_id == aggregate_id]

    def get_all_events(self) -> list[StoredEvent]:
        """Get all events in the store."""
        return list(self._events)

    def clear(self) -> None:
        """Clear all events (for testing)."""
        self._events = []
        self._sequence = 0


class InMemoryEventPublisher(InMemoryAdapter):
    """In-memory event publisher for testing ONLY.

    Implements the EventPublisher protocol. Collects events so that
    sync_published_events_to_projections() can dispatch them to projections.

    Raises:
        InMemoryAdapterError: If instantiated outside test environment.
    """

    def __init__(self) -> None:
        super().__init__()
        self._published_events: list[EventEnvelope[Any]] = []

    async def publish(self, events: list[EventEnvelope[Any]]) -> None:
        """Publish events (stores them in memory for testing)."""
        self._published_events.extend(events)

    def get_published_events(self) -> list[EventEnvelope[Any]]:
        """Get all published events (for testing assertions)."""
        return list(self._published_events)

    def clear(self) -> None:
        """Clear published events (for testing)."""
        self._published_events = []


# ---------------------------------------------------------------------------
# Singleton factory functions (lazy-loaded globals)
# ---------------------------------------------------------------------------

_event_store: InMemoryEventStore | None = None
_event_publisher: InMemoryEventPublisher | None = None


def get_event_store() -> InMemoryEventStore:
    """Get the global in-memory event store (TESTING ONLY)."""
    global _event_store
    if _event_store is None:
        _event_store = InMemoryEventStore()
    return _event_store


def get_event_publisher() -> InMemoryEventPublisher:
    """Get the global in-memory event publisher (TESTING ONLY)."""
    global _event_publisher
    if _event_publisher is None:
        _event_publisher = InMemoryEventPublisher()
    return _event_publisher


def reset_storage() -> None:
    """Reset test utilities (InMemoryEventStore and InMemoryEventPublisher)."""
    if _event_store is not None:
        _event_store.clear()
    if _event_publisher is not None:
        _event_publisher.clear()


__all__ = [
    "InMemoryEventPublisher",
    "InMemoryEventStore",
    "InMemoryStorageError",
    "StoredEvent",
    "get_event_publisher",
    "get_event_store",
    "reset_storage",
]
