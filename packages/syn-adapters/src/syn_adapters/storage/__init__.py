"""Storage adapters — persistence implementations.

All repositories use the SDK's EventStoreRepository, wrapped by RepositoryAdapter.
The event store client (event_store_client.py) is the single decision point:
MemoryEventStoreClient for tests, GrpcEventStoreClient for dev/prod.

See ADR-007: Event Store Integration for architecture details.

Usage:
    from syn_adapters.storage import get_workflow_repository

    repo = get_workflow_repository()
    workflow = await repo.get_by_id(workflow_id)
    await repo.save(workflow)
"""

from __future__ import annotations

from typing import Any

# Event Store Client (SDK-based)
from syn_adapters.storage.event_store_client import (
    connect_event_store,
    disconnect_event_store,
    get_event_store_client,
    reset_event_store_client,
)
from syn_adapters.storage.in_memory import (
    InMemoryEventPublisher,
    InMemoryStorageError,
)

# SDK-based Repositories
from syn_adapters.storage.repositories import (
    get_artifact_repository,
    get_session_repository,
    get_workflow_repository,
    reset_repositories,
)
from syn_shared.settings import get_settings

# Singleton event publisher for test mode
_event_publisher: InMemoryEventPublisher | None = None


class NoOpEventPublisher:
    """No-op event publisher for production.

    In production, projections are updated via EventSubscriptionService
    (ADR-010), not via manual event publishing. This publisher is a no-op.
    """

    async def publish(self, events: list[Any]) -> None:
        """No-op — projections updated via subscription in production."""


def get_event_publisher() -> InMemoryEventPublisher | NoOpEventPublisher:
    """Get the appropriate event publisher based on environment.

    For TEST: Returns InMemoryEventPublisher (for sync_published_events_to_projections).
    For DEV/PROD: Returns NoOpEventPublisher (no-op).
    """
    settings = get_settings()
    if settings.uses_in_memory_stores:
        global _event_publisher
        if _event_publisher is None:
            _event_publisher = InMemoryEventPublisher()
        return _event_publisher
    return NoOpEventPublisher()


def reset_storage() -> None:
    """Reset all storage (for testing between tests).

    Clears:
    1. Event store client cache → new MemoryEventStoreClient (empty streams)
    2. Repository caches → new RepositoryAdapter instances on next access
    3. Event publisher → clear collected events for projection sync
    """
    global _event_publisher

    reset_event_store_client()
    reset_repositories()

    if _event_publisher is not None:
        _event_publisher.clear()


__all__ = [
    "InMemoryEventPublisher",
    "InMemoryStorageError",
    "NoOpEventPublisher",
    "connect_event_store",
    "disconnect_event_store",
    "get_artifact_repository",
    "get_event_publisher",
    "get_event_store_client",
    "get_session_repository",
    "get_workflow_repository",
    "reset_event_store_client",
    "reset_repositories",
    "reset_storage",
]
