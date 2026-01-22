"""Storage adapters - persistence implementations.

This module provides storage adapters based on the event-sourcing-platform SDK.
See ADR-007: Event Store Integration for architecture details.

Environment-based selection:
- **TEST** (APP_ENVIRONMENT=test): Uses SDK's MemoryEventStoreClient
  Fast, isolated, no external dependencies. For unit tests only.

- **DEVELOPMENT/PRODUCTION**: Uses SDK's GrpcEventStoreClient
  Connects to Event Store Server via gRPC (port 50051).
  Event Store Server persists to PostgreSQL.
  Start with: just dev

Usage:
    from aef_adapters.storage import get_workflow_repository

    # Get repository (auto-selects client based on environment)
    repo = get_workflow_repository()

    # Use repository
    workflow = await repo.load(workflow_id)
    await repo.save(workflow)
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

# Event Store Client (SDK-based)
from aef_adapters.storage.event_store_client import (
    connect_event_store,
    disconnect_event_store,
    get_event_store_client,
    reset_event_store_client,
)

# Legacy in-memory implementations (for backwards compatibility and test utilities)
from aef_adapters.storage.in_memory import (
    InMemoryArtifactRepository,
    InMemoryEventPublisher,
    InMemoryEventStore,
    InMemorySessionRepository,
    InMemoryStorageError,
    InMemoryWorkflowRepository,
    StoredEvent,
    get_event_store,
)
from aef_adapters.storage.in_memory import (
    get_event_publisher as get_inmem_event_publisher,
)
from aef_adapters.storage.in_memory import (
    reset_storage as reset_legacy_storage,
)

# SDK-based Repositories
from aef_adapters.storage.repositories import (
    get_artifact_repository,
    get_session_repository,
    get_workflow_repository,
    reset_repositories,
)
from aef_shared.settings import get_settings

if TYPE_CHECKING:
    from aef_domain.contexts.artifacts._shared.ArtifactAggregate import (
        ArtifactAggregate,
    )
    from aef_domain.contexts.sessions.domain.AgentSessionAggregate import (
        AgentSessionAggregate,
    )
    from aef_domain.contexts.workflows._shared.WorkflowAggregate import (
        WorkflowAggregate,
    )


class NoOpEventPublisher:
    """Minimal event publisher for SDK-based repositories.

    With the subscription-based architecture (ADR-010), projections are
    updated via EventSubscriptionService which subscribes to the event store.
    This publisher exists for backwards compatibility and logging only.

    The actual projection updates happen through:
    1. Repository saves event to Event Store (via SDK)
    2. EventSubscriptionService receives event via subscription
    3. EventSubscriptionService dispatches to ProjectionManager

    See: EventSubscriptionService, ADR-010
    """

    async def publish(self, events: list[Any]) -> None:
        """Log event publication - projections updated via subscription.

        Args:
            events: Events that were persisted to the event store.
        """
        import logging

        logger = logging.getLogger(__name__)
        if events:
            logger.debug(
                "Events persisted to event store (projections updated via subscription)",
                extra={"event_count": len(events)},
            )


def get_event_publisher() -> InMemoryEventPublisher | NoOpEventPublisher:
    """Get the appropriate event publisher based on environment.

    For TEST: Returns InMemoryEventPublisher (for test assertions).
    For DEV/PROD: Returns NoOpEventPublisher (SDK handles persistence).
    """
    settings = get_settings()
    if settings.is_test:
        return get_inmem_event_publisher()
    return NoOpEventPublisher()


# Repository protocols for type checking (backwards compatibility)
class WorkflowRepositoryProtocol(Protocol):
    """Protocol for workflow repositories."""

    async def load(self, aggregate_id: str) -> WorkflowAggregate | None: ...
    async def save(self, aggregate: WorkflowAggregate) -> None: ...
    async def exists(self, aggregate_id: str) -> bool: ...


class SessionRepositoryProtocol(Protocol):
    """Protocol for session repositories."""

    async def load(self, aggregate_id: str) -> AgentSessionAggregate | None: ...
    async def save(self, aggregate: AgentSessionAggregate) -> None: ...
    async def exists(self, aggregate_id: str) -> bool: ...


class ArtifactRepositoryProtocol(Protocol):
    """Protocol for artifact repositories."""

    async def load(self, aggregate_id: str) -> ArtifactAggregate | None: ...
    async def save(self, aggregate: ArtifactAggregate) -> None: ...
    async def exists(self, aggregate_id: str) -> bool: ...


def reset_storage() -> None:
    """Reset all storage (for testing).

    Clears:
    - Event store client cache
    - Repository caches
    - Legacy in-memory storage (if used)
    """
    reset_event_store_client()
    reset_repositories()
    reset_legacy_storage()


__all__ = [
    # Protocols
    "ArtifactRepositoryProtocol",
    # Legacy in-memory (for backwards compatibility / test utilities)
    "InMemoryArtifactRepository",
    "InMemoryEventPublisher",
    "InMemoryEventStore",
    "InMemorySessionRepository",
    "InMemoryStorageError",
    "InMemoryWorkflowRepository",
    "NoOpEventPublisher",
    "SessionRepositoryProtocol",
    "StoredEvent",
    "WorkflowRepositoryProtocol",
    # SDK-based (preferred)
    "connect_event_store",
    "disconnect_event_store",
    "get_artifact_repository",
    "get_event_publisher",
    "get_event_store",
    "get_event_store_client",
    "get_session_repository",
    "get_workflow_repository",
    "reset_event_store_client",
    "reset_repositories",
    "reset_storage",
]
