"""UpdateWorkflowPhase handler - thin application service adapter."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from event_sourcing import DomainEvent, EventEnvelope

    from syn_domain.contexts.orchestration.domain.aggregate_workflow_template.WorkflowTemplateAggregate import (
        WorkflowTemplateAggregate,
    )
    from syn_domain.contexts.orchestration.domain.commands.UpdatePhasePromptCommand import (
        UpdatePhasePromptCommand,
    )


class WorkflowRepository(Protocol):
    """Repository protocol for Workflow aggregates."""

    async def get_by_id(self, aggregate_id: str) -> WorkflowTemplateAggregate | None:
        """Load an aggregate by ID."""
        ...

    async def save(self, aggregate: WorkflowTemplateAggregate) -> None:
        """Save the aggregate and its uncommitted events."""
        ...


class EventPublisher(Protocol):
    """Protocol for publishing domain events."""

    async def publish(self, events: list[EventEnvelope[DomainEvent]]) -> None:
        """Publish domain events for integration."""
        ...


class UpdateWorkflowPhaseHandler:
    """Application service handler for UpdatePhasePromptCommand.

    This is a thin adapter that:
    1. Loads the existing aggregate
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

    async def handle(self, command: UpdatePhasePromptCommand) -> str:
        """Handle the UpdatePhasePromptCommand.

        Returns:
            The workflow ID.

        Raises:
            ValueError: If workflow not found or phase_id invalid.
        """
        # Load existing aggregate
        aggregate = await self._repository.get_by_id(command.aggregate_id)
        if aggregate is None:
            msg = f"Workflow '{command.aggregate_id}' not found"
            raise ValueError(msg)

        # Dispatch command to aggregate (uses @command_handler decorator)
        aggregate._handle_command(command)

        # Persist via repository
        await self._repository.save(aggregate)

        # Publish events for integration with other bounded contexts
        events = aggregate.get_uncommitted_events()
        await self._event_publisher.publish(events)  # type: ignore[arg-type]  # generic covariance

        # Clear events after publishing
        aggregate.mark_events_as_committed()

        return command.aggregate_id
