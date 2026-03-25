"""Query helpers for InMemoryWorkflowRepository (TESTING ONLY).

Extracted from in_memory_workflow_repo.py to reduce module complexity.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Sequence
    from uuid import UUID

    from event_sourcing import EventEnvelope

    from syn_adapters.storage.in_memory import InMemoryEventStore
    from syn_domain.contexts.orchestration.domain.aggregate_workflow_template.WorkflowTemplateAggregate import (
        WorkflowTemplateAggregate,
    )


async def get_workflow_by_id(
    event_store: InMemoryEventStore, workflow_id: str | UUID
) -> WorkflowTemplateAggregate | None:
    """Retrieve a workflow by ID, replaying events."""
    from event_sourcing import EventEnvelope, EventMetadata

    from syn_domain.contexts.orchestration.domain.aggregate_workflow_template.WorkflowTemplateAggregate import (
        WorkflowTemplateAggregate,
    )
    from syn_domain.contexts.orchestration.domain.events.WorkflowTemplateCreatedEvent import (
        WorkflowTemplateCreatedEvent,
    )

    str_id = str(workflow_id)
    stored_events = event_store.get_events(str_id)

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


def _build_envelopes(
    stored_events: Sequence[object],
) -> list[EventEnvelope[Any]]:
    """Build EventEnvelope list from stored events for a single aggregate."""
    from event_sourcing import EventEnvelope, EventMetadata

    from syn_domain.contexts.orchestration.domain.events.WorkflowTemplateCreatedEvent import (
        WorkflowTemplateCreatedEvent,
    )

    envelopes: list[EventEnvelope[Any]] = []
    for stored_event in stored_events:
        if stored_event.event_type != "WorkflowTemplateCreated":  # type: ignore[union-attr]
            continue
        workflow_event = WorkflowTemplateCreatedEvent(**stored_event.event_data)  # type: ignore[union-attr]
        metadata = EventMetadata(
            event_id=f"evt-{stored_event.sequence}",  # type: ignore[union-attr]
            aggregate_id=stored_event.aggregate_id,  # type: ignore[union-attr]
            aggregate_type=stored_event.aggregate_type,  # type: ignore[union-attr]
            aggregate_nonce=stored_event.version,  # type: ignore[union-attr]
        )
        envelopes.append(EventEnvelope(event=workflow_event, metadata=metadata))
    return envelopes


def get_all_workflows(event_store: InMemoryEventStore) -> list[WorkflowTemplateAggregate]:
    """Get all workflows."""
    from syn_domain.contexts.orchestration.domain.aggregate_workflow_template.WorkflowTemplateAggregate import (
        WorkflowTemplateAggregate,
    )

    # Get unique aggregate IDs
    aggregate_ids: set[str] = set()
    for event in event_store.get_all_events():
        if event.aggregate_type == "WorkflowTemplate":
            aggregate_ids.add(event.aggregate_id)

    workflows: list[WorkflowTemplateAggregate] = []
    for agg_id in aggregate_ids:
        stored_events = event_store.get_events(agg_id)
        if not stored_events:
            continue

        envelopes = _build_envelopes(stored_events)
        if envelopes:
            aggregate = WorkflowTemplateAggregate()
            aggregate.rehydrate(envelopes)
            workflows.append(aggregate)

    return workflows
