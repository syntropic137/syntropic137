"""In-memory storage adapters for TESTING ONLY.

WARNING: These adapters are for unit/integration tests only.
For local development, use Docker with PostgreSQL (see docker/docker-compose.dev.yaml).
For production, use the real event store and PostgreSQL.

The in-memory store:
- Does NOT persist between process restarts
- Is NOT thread-safe
- Should NEVER be used outside of tests
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from uuid import UUID

    from event_sourcing import EventEnvelope

    from aef_domain.contexts.workflows._shared.WorkflowAggregate import (
        WorkflowAggregate,
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
    """

    _events: list[StoredEvent] = field(default_factory=list)
    _sequence: int = field(default=0)

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
    """

    def __init__(self, event_store: InMemoryEventStore) -> None:
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
        from aef_domain.contexts.workflows.create_workflow.WorkflowCreatedEvent import (
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


class InMemoryEventPublisher:
    """In-memory event publisher for testing and development.

    Implements the EventPublisher protocol. In production, this would
    publish to a message broker (e.g., RabbitMQ, Kafka).
    """

    def __init__(self) -> None:
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


# Global instances for simple DI (replace with proper DI in production)
_event_store = InMemoryEventStore()
_workflow_repository = InMemoryWorkflowRepository(_event_store)
_event_publisher = InMemoryEventPublisher()


def get_event_store() -> InMemoryEventStore:
    """Get the global in-memory event store."""
    return _event_store


def get_workflow_repository() -> InMemoryWorkflowRepository:
    """Get the global in-memory workflow repository."""
    return _workflow_repository


def get_event_publisher() -> InMemoryEventPublisher:
    """Get the global in-memory event publisher."""
    return _event_publisher


def reset_storage() -> None:
    """Reset all storage (for testing between tests)."""
    _event_store.clear()
    _event_publisher.clear()
