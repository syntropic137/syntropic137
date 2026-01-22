"""In-memory storage adapters for TESTING ONLY.

WARNING: These adapters are for unit/integration tests only.
For local development, use Docker with PostgreSQL (see docker/docker-compose.dev.yaml).
For production, use the real event store and PostgreSQL.

The in-memory store:
- Does NOT persist between process restarts
- Is NOT thread-safe
- Should NEVER be used outside of tests
- Will raise an error if used in non-test environments
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from aef_shared.settings import get_settings

if TYPE_CHECKING:
    from uuid import UUID

    from event_sourcing import EventEnvelope

    from aef_domain.contexts.artifacts._shared.ArtifactAggregate import (
        ArtifactAggregate,
    )
    from aef_domain.contexts.sessions.domain.AgentSessionAggregate import (
        AgentSessionAggregate,
    )
    from aef_domain.contexts.workflows._shared.WorkflowAggregate import (
        WorkflowAggregate,
    )
    from aef_domain.contexts.workflows._shared.WorkflowExecutionAggregate import (
        WorkflowExecutionAggregate,
    )


class InMemoryStorageError(Exception):
    """Raised when in-memory storage is used outside of test environment."""

    pass


def _assert_test_environment() -> None:
    """Assert that we're in a test environment.

    Raises:
        InMemoryStorageError: If not in test environment (APP_ENVIRONMENT != 'test').
    """
    settings = get_settings()
    if not settings.is_test:
        raise InMemoryStorageError(
            "In-memory storage can ONLY be used in test environments. "
            f"Current environment: {settings.app_environment}. "
            "For local development, use PostgreSQL via 'just dev'. "
            "Set APP_ENVIRONMENT=test to use in-memory storage for unit tests."
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


class InMemoryWorkflowRepository:
    """In-memory repository for Workflow aggregates.

    Implements the WorkflowRepository protocol defined in the handler.

    Raises:
        InMemoryStorageError: If instantiated outside test environment.
    """

    def __init__(self, event_store: InMemoryEventStore) -> None:
        _assert_test_environment()
        self._event_store = event_store

    async def save(self, aggregate: WorkflowAggregate) -> None:
        """Save the aggregate's uncommitted events to the store."""
        events = aggregate.get_uncommitted_events()

        for i, event_envelope in enumerate(events):
            event = event_envelope.event
            # Extract event data for storage
            event_data = event.model_dump() if hasattr(event, "model_dump") else {}

            self._event_store.append(
                aggregate_id=str(aggregate.id) if aggregate.id else "",
                aggregate_type=aggregate.get_aggregate_type(),
                event_type=getattr(event, "event_type", type(event).__name__),
                event_data=event_data,
                version=aggregate.version + i + 1,
            )

    async def get_by_id(self, workflow_id: str | UUID) -> WorkflowAggregate | None:
        """Retrieve a workflow by ID, replaying events."""
        from event_sourcing import EventEnvelope, EventMetadata

        from aef_domain.contexts.workflows._shared.WorkflowAggregate import (
            WorkflowAggregate,
        )
        from aef_domain.contexts.workflows.domain.events.WorkflowCreatedEvent import (
            WorkflowCreatedEvent,
        )

        str_id = str(workflow_id)
        stored_events = self._event_store.get_events(str_id)

        if not stored_events:
            return None

        # Reconstruct aggregate from events using SDK's rehydrate method
        aggregate = WorkflowAggregate()

        # Build EventEnvelope list for rehydration
        envelopes: list[EventEnvelope[WorkflowCreatedEvent]] = []
        for stored_event in stored_events:
            if stored_event.event_type == "WorkflowCreated":
                # Reconstruct the event from stored data
                event = WorkflowCreatedEvent(**stored_event.event_data)
                metadata = EventMetadata(
                    event_id=f"evt-{stored_event.sequence}",
                    aggregate_id=stored_event.aggregate_id,
                    aggregate_type=stored_event.aggregate_type,
                    aggregate_nonce=stored_event.version,
                )
                envelope = EventEnvelope(event=event, metadata=metadata)
                envelopes.append(envelope)

        # Use SDK's rehydrate method for proper event sourcing replay
        aggregate.rehydrate(envelopes)

        return aggregate

    def get_all(self) -> list[WorkflowAggregate]:
        """Get all workflows."""
        from event_sourcing import EventEnvelope, EventMetadata

        from aef_domain.contexts.workflows._shared.WorkflowAggregate import (
            WorkflowAggregate,
        )
        from aef_domain.contexts.workflows.domain.events.WorkflowCreatedEvent import (
            WorkflowCreatedEvent,
        )

        # Get unique aggregate IDs
        aggregate_ids: set[str] = set()
        for event in self._event_store.get_all_events():
            if event.aggregate_type == "Workflow":
                aggregate_ids.add(event.aggregate_id)

        workflows: list[WorkflowAggregate] = []
        for agg_id in aggregate_ids:
            stored_events = self._event_store.get_events(agg_id)
            if not stored_events:
                continue

            aggregate = WorkflowAggregate()
            envelopes: list[EventEnvelope[Any]] = []
            for stored_event in stored_events:
                if stored_event.event_type == "WorkflowCreated":
                    workflow_event = WorkflowCreatedEvent(**stored_event.event_data)
                    metadata = EventMetadata(
                        event_id=f"evt-{stored_event.sequence}",
                        aggregate_id=stored_event.aggregate_id,
                        aggregate_type=stored_event.aggregate_type,
                        aggregate_nonce=stored_event.version,
                    )
                    envelope: EventEnvelope[Any] = EventEnvelope(
                        event=workflow_event, metadata=metadata
                    )
                    envelopes.append(envelope)

            if envelopes:
                aggregate.rehydrate(envelopes)
                workflows.append(aggregate)

        return workflows


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


class InMemorySessionRepository:
    """In-memory repository for AgentSession aggregates.

    Used for testing ONLY.

    Raises:
        InMemoryStorageError: If instantiated outside test environment.
    """

    def __init__(self) -> None:
        _assert_test_environment()
        self._sessions: dict[str, AgentSessionAggregate] = {}

    async def save(self, aggregate: AgentSessionAggregate) -> None:
        """Save the session aggregate."""
        if aggregate.id:
            self._sessions[str(aggregate.id)] = aggregate
            aggregate.mark_events_as_committed()

    async def get(self, session_id: str) -> AgentSessionAggregate | None:
        """Get session by ID."""
        return self._sessions.get(session_id)

    def get_all(self) -> list[AgentSessionAggregate]:
        """Get all sessions."""
        return list(self._sessions.values())

    def get_by_workflow(self, workflow_id: str) -> list[AgentSessionAggregate]:
        """Get all sessions for a workflow."""
        return [s for s in self._sessions.values() if s.workflow_id == workflow_id]

    def clear(self) -> None:
        """Clear all sessions."""
        self._sessions = {}


class InMemoryArtifactRepository:
    """In-memory repository for Artifact aggregates.

    Used for testing ONLY.

    Raises:
        InMemoryStorageError: If instantiated outside test environment.
    """

    def __init__(self) -> None:
        _assert_test_environment()
        self._artifacts: dict[str, ArtifactAggregate] = {}

    async def save(self, aggregate: ArtifactAggregate) -> None:
        """Save the artifact aggregate."""
        if aggregate.id:
            self._artifacts[str(aggregate.id)] = aggregate
            aggregate.mark_events_as_committed()

    async def get(self, artifact_id: str) -> ArtifactAggregate | None:
        """Get artifact by ID."""
        return self._artifacts.get(artifact_id)

    def get_all(self) -> list[ArtifactAggregate]:
        """Get all artifacts."""
        return list(self._artifacts.values())

    def get_by_workflow(self, workflow_id: str) -> list[ArtifactAggregate]:
        """Get all artifacts for a workflow."""
        return [a for a in self._artifacts.values() if a.workflow_id == workflow_id]

    def get_by_phase(self, workflow_id: str, phase_id: str) -> list[ArtifactAggregate]:
        """Get all artifacts for a specific phase."""
        return [
            a
            for a in self._artifacts.values()
            if a.workflow_id == workflow_id and a.phase_id == phase_id
        ]

    def clear(self) -> None:
        """Clear all artifacts."""
        self._artifacts = {}


class InMemoryWorkflowExecutionRepository:
    """In-memory repository for WorkflowExecution aggregates.

    Used for testing ONLY.

    Raises:
        InMemoryStorageError: If instantiated outside test environment.
    """

    def __init__(self) -> None:
        _assert_test_environment()
        self._executions: dict[str, WorkflowExecutionAggregate] = {}

    async def save(self, aggregate: WorkflowExecutionAggregate) -> None:
        """Save the execution aggregate."""
        if aggregate.id:
            self._executions[str(aggregate.id)] = aggregate
            aggregate.mark_events_as_committed()

    async def get_by_id(self, execution_id: str) -> WorkflowExecutionAggregate | None:
        """Get execution by ID."""
        return self._executions.get(execution_id)

    async def exists(self, execution_id: str) -> bool:
        """Check if execution exists."""
        return execution_id in self._executions

    def get_all(self) -> list[WorkflowExecutionAggregate]:
        """Get all executions."""
        return list(self._executions.values())

    def get_by_workflow(self, workflow_id: str) -> list[WorkflowExecutionAggregate]:
        """Get all executions for a workflow."""
        return [e for e in self._executions.values() if e.workflow_id == workflow_id]

    def clear(self) -> None:
        """Clear all executions."""
        self._executions = {}


# Lazy-loaded global instances for simple DI (test environments only)
# These are created on first access, not at module import time
_event_store: InMemoryEventStore | None = None
_workflow_repository: InMemoryWorkflowRepository | None = None
_workflow_execution_repository: InMemoryWorkflowExecutionRepository | None = None
_event_publisher: InMemoryEventPublisher | None = None
_session_repository: InMemorySessionRepository | None = None
_artifact_repository: InMemoryArtifactRepository | None = None


def get_event_store() -> InMemoryEventStore:
    """Get the global in-memory event store.

    Raises:
        InMemoryStorageError: If not in test environment.
    """
    global _event_store
    if _event_store is None:
        _event_store = InMemoryEventStore()
    return _event_store


def get_workflow_repository() -> InMemoryWorkflowRepository:
    """Get the global in-memory workflow repository.

    Raises:
        InMemoryStorageError: If not in test environment.
    """
    global _workflow_repository
    if _workflow_repository is None:
        _workflow_repository = InMemoryWorkflowRepository(get_event_store())
    return _workflow_repository


def get_event_publisher() -> InMemoryEventPublisher:
    """Get the global in-memory event publisher.

    Raises:
        InMemoryStorageError: If not in test environment.
    """
    global _event_publisher
    if _event_publisher is None:
        _event_publisher = InMemoryEventPublisher()
    return _event_publisher


def get_session_repository() -> InMemorySessionRepository:
    """Get the global in-memory session repository.

    Raises:
        InMemoryStorageError: If not in test environment.
    """
    global _session_repository
    if _session_repository is None:
        _session_repository = InMemorySessionRepository()
    return _session_repository


def get_artifact_repository() -> InMemoryArtifactRepository:
    """Get the global in-memory artifact repository.

    Raises:
        InMemoryStorageError: If not in test environment.
    """
    global _artifact_repository
    if _artifact_repository is None:
        _artifact_repository = InMemoryArtifactRepository()
    return _artifact_repository


def get_workflow_execution_repository() -> InMemoryWorkflowExecutionRepository:
    """Get the global in-memory workflow execution repository.

    Raises:
        InMemoryStorageError: If not in test environment.
    """
    global _workflow_execution_repository
    if _workflow_execution_repository is None:
        _workflow_execution_repository = InMemoryWorkflowExecutionRepository()
    return _workflow_execution_repository


def reset_storage() -> None:
    """Reset all storage (for testing between tests).

    Clears all in-memory stores if they have been initialized.
    """
    if _event_store is not None:
        _event_store.clear()
    if _event_publisher is not None:
        _event_publisher.clear()
    if _session_repository is not None:
        _session_repository.clear()
    if _artifact_repository is not None:
        _artifact_repository.clear()
    if _workflow_execution_repository is not None:
        _workflow_execution_repository.clear()
