"""In-memory storage adapters for TESTING ONLY.

WARNING: These adapters are for unit/integration tests only.
For local development, use Docker with PostgreSQL (see docker/docker-compose.dev.yaml).
For production, use the real event store and PostgreSQL.

The in-memory store:
- Does NOT persist between process restarts
- Is NOT thread-safe
- Should NEVER be used outside of tests
- Will raise an error if used in non-test environments

This module contains the core event store, event publisher, and test-environment
guard. Repository classes are in in_memory_repositories.py and singleton
factory functions are in in_memory_factories.py. All symbols are re-exported
here for backwards compatibility.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from syn_shared.settings import get_settings

if TYPE_CHECKING:
    from event_sourcing import EventEnvelope


class InMemoryStorageError(Exception):
    """Raised when in-memory storage is used outside of test environment."""

    pass


def _assert_test_environment() -> None:
    """Assert that we're in a test or offline environment.

    Raises:
        InMemoryStorageError: If not in test/offline environment.
    """
    settings = get_settings()
    if not settings.uses_in_memory_stores:
        raise InMemoryStorageError(
            "In-memory storage can ONLY be used in test or offline environments. "
            f"Current environment: {settings.app_environment}. "
            "For local development, use PostgreSQL via 'just dev'. "
            "Set APP_ENVIRONMENT=test or APP_ENVIRONMENT=offline to use in-memory storage."
        )


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

    ⚠️  WARNING: Do NOT use for local development!
    Use Docker + PostgreSQL for local dev to mirror production.

    This is NOT thread-safe and should only be used for:
    - Unit tests (fast, isolated)
    - Integration tests (when mocking external deps)

    For local development: docker/docker-compose.dev.yaml
    For production: Real PostgreSQL event store

    Raises:
        InMemoryStorageError: If instantiated outside test environment.
    """

    _events: list[StoredEvent] = field(default_factory=list)
    _sequence: int = field(default=0)

    def __post_init__(self) -> None:
        """Validate environment on initialization."""
        _assert_test_environment()

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


class InMemoryEventPublisher:
    """In-memory event publisher for testing ONLY.

    Implements the EventPublisher protocol. In production, this would
    publish to a message broker (e.g., RabbitMQ, Kafka).

    Raises:
        InMemoryStorageError: If instantiated outside test environment.
    """

    def __init__(self) -> None:
        _assert_test_environment()
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
# Backwards-compatibility re-exports
#
# External code (repositories.py, _wiring.py, tests, collector) imports
# repository classes and factory functions from this module. Re-export
# everything so those imports continue to work without modification.
# ---------------------------------------------------------------------------

from syn_adapters.storage.in_memory_factories import (  # noqa: E402
    get_artifact_repository,
    get_event_publisher,
    get_event_store,
    get_organization_repository,
    get_repo_repository,
    get_session_repository,
    get_system_repository,
    get_workflow_execution_repository,
    get_workflow_repository,
    reset_storage,
)
from syn_adapters.storage.in_memory_repositories import (  # noqa: E402
    InMemoryArtifactRepository,
    InMemoryOrganizationRepository,
    InMemoryRepoRepository,
    InMemorySessionRepository,
    InMemorySystemRepository,
    InMemoryWorkflowExecutionRepository,
    InMemoryWorkflowRepository,
)

__all__ = [
    "InMemoryArtifactRepository",
    "InMemoryEventPublisher",
    "InMemoryEventStore",
    "InMemoryOrganizationRepository",
    "InMemoryRepoRepository",
    "InMemorySessionRepository",
    # Core (defined here)
    "InMemoryStorageError",
    "InMemorySystemRepository",
    "InMemoryWorkflowExecutionRepository",
    # Re-exported repositories
    "InMemoryWorkflowRepository",
    "StoredEvent",
    "_assert_test_environment",
    "get_artifact_repository",
    "get_event_publisher",
    # Re-exported factories
    "get_event_store",
    "get_organization_repository",
    "get_repo_repository",
    "get_session_repository",
    "get_system_repository",
    "get_workflow_execution_repository",
    "get_workflow_repository",
    "reset_storage",
]
