"""CreateWorkflow handler - thin application service adapter."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from aef_domain.contexts.workflows._shared.WorkflowAggregate import WorkflowAggregate

if TYPE_CHECKING:
    from event_sourcing import EventEnvelope

    from aef_domain.contexts.workflows.domain.events.WorkflowCreatedEvent import (
        WorkflowCreatedEvent,
    )
    from aef_domain.contexts.workflows.slices.create_workflow.CreateWorkflowCommand import (
        CreateWorkflowCommand,
    )


class WorkflowRepository(Protocol):
    """Repository protocol for Workflow aggregates."""

    async def save(self, aggregate: WorkflowAggregate) -> None:
        """Save the aggregate and its uncommitted events."""
        ...


class EventPublisher(Protocol):
    """Protocol for publishing domain events."""

    async def publish(self, events: list[EventEnvelope[WorkflowCreatedEvent]]) -> None:
        """Publish domain events for integration."""
        ...


class CreateWorkflowHandler:
    """Application service handler for CreateWorkflowCommand.

    This is a thin adapter that:
    1. Creates the aggregate
    2. Dispatches the command to aggregate's @command_handler
    3. Persists events via repository
    4. Publishes events for integration
    """

    def __init__(
        self,
        repository: WorkflowRepository,
        event_publisher: EventPublisher,
    ) -> None:
        self._repository = repository
        self._event_publisher = event_publisher

    async def handle(self, command: CreateWorkflowCommand) -> str:
        """Handle the CreateWorkflowCommand.

        Returns:
            The created workflow ID.
        """
        # Create new aggregate
        aggregate = WorkflowAggregate()

        # Dispatch command to aggregate (uses @command_handler decorator)
        aggregate._handle_command(command)

        # Persist via repository
        await self._repository.save(aggregate)

        # Publish events for integration with other bounded contexts
        events = aggregate.get_uncommitted_events()
        await self._event_publisher.publish(events)

        # Clear events after publishing
        aggregate.mark_events_as_committed()

        # Return the new workflow ID
        workflow_id = aggregate.id
        if workflow_id is None:
            msg = "Workflow ID should not be None after creation"
            raise RuntimeError(msg)

        return workflow_id
