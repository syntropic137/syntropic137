"""In-memory repository for WorkflowTemplate aggregates (TESTING ONLY).

Extracted from in_memory_repo_helpers.py to reduce module complexity.

WARNING: This repository is for unit/integration tests only.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from syn_adapters.storage.in_memory import InMemoryEventStore, _assert_test_environment

if TYPE_CHECKING:
    from uuid import UUID

    from event_sourcing import EventEnvelope

    from syn_domain.contexts.orchestration.domain.aggregate_workflow_template.WorkflowTemplateAggregate import (
        WorkflowTemplateAggregate,
    )


class InMemoryWorkflowRepository:
    """In-memory repository for Workflow aggregates.

    Implements the WorkflowRepository protocol defined in the handler.

    Raises:
        InMemoryStorageError: If instantiated outside test environment.
    """

    def __init__(self, event_store: InMemoryEventStore) -> None:
        _assert_test_environment()
        self._event_store = event_store

    async def save(self, aggregate: WorkflowTemplateAggregate) -> None:
        """Save the aggregate's uncommitted events to the store."""
        events = aggregate.get_uncommitted_events()

        for i, event_envelope in enumerate(events):
            event = event_envelope.event
            # Extract event data for storage
            event_data = event.model_dump() if hasattr(event, "model_dump") else {}

            self._event_store.append(
                aggregate_id=str(aggregate.id) if aggregate.id else "",
                aggregate_type=aggregate.get_aggregate_type(),
                event_type=event.event_type
                if hasattr(event, "event_type")
                else type(event).__name__,
                event_data=event_data,
                version=aggregate.version + i + 1,
            )

    async def exists(self, workflow_id: str | UUID) -> bool:
        """Check if a workflow exists by ID."""
        str_id = str(workflow_id)
        stored_events = self._event_store.get_events(str_id)
        return len(stored_events) > 0

    async def get_by_id(self, workflow_id: str | UUID) -> WorkflowTemplateAggregate | None:
        """Retrieve a workflow by ID, replaying events."""
        from event_sourcing import EventEnvelope, EventMetadata

        from syn_domain.contexts.orchestration.domain.aggregate_workflow_template.WorkflowTemplateAggregate import (
            WorkflowTemplateAggregate,
        )
        from syn_domain.contexts.orchestration.domain.events.WorkflowTemplateCreatedEvent import (
            WorkflowTemplateCreatedEvent,
        )

        str_id = str(workflow_id)
        stored_events = self._event_store.get_events(str_id)

        if not stored_events:
            return None

        # Reconstruct aggregate from events using SDK's rehydrate method
        aggregate = WorkflowTemplateAggregate()

        # Build EventEnvelope list for rehydration
        envelopes: list[EventEnvelope[WorkflowTemplateCreatedEvent]] = []
        for stored_event in stored_events:
            if stored_event.event_type == "WorkflowTemplateCreated":
                # Reconstruct the event from stored data
                event = WorkflowTemplateCreatedEvent(**stored_event.event_data)
                metadata = EventMetadata(
                    event_id=f"evt-{stored_event.sequence}",
                    aggregate_id=stored_event.aggregate_id,
                    aggregate_type=stored_event.aggregate_type,
                    aggregate_nonce=stored_event.version,
                )
                envelope = EventEnvelope(event=event, metadata=metadata)
                envelopes.append(envelope)

        # Use SDK's rehydrate method for proper event sourcing replay
        aggregate.rehydrate(envelopes)  # type: ignore[arg-type]  # generic covariance: list[EventEnvelope[SpecificEvent]] is compatible with list[EventEnvelope[DomainEvent]]

        return aggregate

    def get_all(self) -> list[WorkflowTemplateAggregate]:
        """Get all workflows."""
        from event_sourcing import EventEnvelope, EventMetadata

        from syn_domain.contexts.orchestration.domain.aggregate_workflow_template.WorkflowTemplateAggregate import (
            WorkflowTemplateAggregate,
        )
        from syn_domain.contexts.orchestration.domain.events.WorkflowTemplateCreatedEvent import (
            WorkflowTemplateCreatedEvent,
        )

        # Get unique aggregate IDs
        aggregate_ids: set[str] = set()
        for event in self._event_store.get_all_events():
            if event.aggregate_type == "WorkflowTemplate":
                aggregate_ids.add(event.aggregate_id)

        workflows: list[WorkflowTemplateAggregate] = []
        for agg_id in aggregate_ids:
            stored_events = self._event_store.get_events(agg_id)
            if not stored_events:
                continue

            aggregate = WorkflowTemplateAggregate()
            envelopes: list[EventEnvelope[Any]] = []
            for stored_event in stored_events:
                if stored_event.event_type == "WorkflowTemplateCreated":
                    workflow_event = WorkflowTemplateCreatedEvent(**stored_event.event_data)
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
