"""Singleton factory functions for in-memory test utilities.

Provides lazy-loaded global instances for InMemoryEventStore and
InMemoryEventPublisher. These are used for test utilities only —
all repositories now go through the SDK's EventStoreRepository
backed by MemoryEventStoreClient (see repositories.py).
"""

from __future__ import annotations

from syn_adapters.storage.in_memory import InMemoryEventPublisher, InMemoryEventStore

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
