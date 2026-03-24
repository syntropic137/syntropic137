"""In-memory repository for WorkflowTemplate aggregates (TESTING ONLY).

Extracted from in_memory_repo_helpers.py to reduce module complexity.

WARNING: This repository is for unit/integration tests only.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syn_adapters.storage.in_memory import InMemoryEventStore, _assert_test_environment

if TYPE_CHECKING:
    from uuid import UUID

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
        from syn_adapters.storage.in_memory_workflow_repo_queries import get_workflow_by_id

        return await get_workflow_by_id(self._event_store, workflow_id)

    def get_all(self) -> list[WorkflowTemplateAggregate]:
        """Get all workflows."""
        from syn_adapters.storage.in_memory_workflow_repo_queries import get_all_workflows

        return get_all_workflows(self._event_store)
