"""UpdateWorkflowPhase handler - thin application service adapter."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from syn_shared.agents import AgentProvider, normalize_phase_model

if TYPE_CHECKING:
    from event_sourcing import DomainEvent, EventEnvelope

    from syn_domain.contexts.orchestration.domain.aggregate_workflow_template.value_objects import (
        PhaseDefinition,
    )
    from syn_domain.contexts.orchestration.domain.aggregate_workflow_template.WorkflowTemplateAggregate import (
        WorkflowTemplateAggregate,
    )
    from syn_domain.contexts.orchestration.domain.commands.UpdatePhasePromptCommand import (
        UpdatePhasePromptCommand,
    )
    from syn_shared.agents import PhaseModelDefaults


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

    Like install, this is a write boundary for the phase's model: the edit is
    normalised against the phase's EFFECTIVE provider before it is recorded,
    with the same rule (``normalize_phase_model``) and the operator's
    configured ``model_defaults``. Without it a provider switch persisted the
    old provider's model (``opus`` on a codex phase) and a legacy phase kept
    ``model=None`` through every edit.
    """

    def __init__(
        self,
        repository: WorkflowRepository,
        event_publisher: EventPublisher,
        *,
        model_defaults: PhaseModelDefaults,
    ) -> None:
        self._repository = repository
        self._event_publisher = event_publisher
        self._model_defaults = model_defaults

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

        current = next((p for p in aggregate.phases if p.phase_id == command.phase_id), None)
        if current is not None:
            command = _normalise_model(command, current, self._model_defaults)

        # Dispatch command to aggregate (uses @command_handler decorator).
        # An unknown phase_id is left for the aggregate to refuse.
        aggregate.update_phase_prompt(command)

        # Persist via repository
        await self._repository.save(aggregate)

        # Publish events for integration with other bounded contexts
        events = aggregate.get_uncommitted_events()
        await self._event_publisher.publish(events)  # type: ignore[arg-type]  # generic covariance

        # Clear events after publishing
        aggregate.mark_events_as_committed()

        return command.aggregate_id


def _effective_provider(provider: str | None) -> str:
    return provider or AgentProvider.CLAUDE


def _normalise_model(
    command: UpdatePhasePromptCommand,
    current: PhaseDefinition,
    defaults: PhaseModelDefaults,
) -> UpdatePhasePromptCommand:
    """Resolve the model this edit leaves the phase with, and its provenance.

    The candidate is the model the edit names; failing that, the stored one -
    EXCEPT when the edit switches provider and the stored model was only a
    default: a default is chosen per provider, so it does not survive the
    switch (an operator default may be a string the table cannot judge, which
    the wrong-provider check alone would keep). A declared model is carried
    across and then judged like any other.
    """
    provider = command.provider if command.provider is not None else current.provider
    switched = _effective_provider(provider) != _effective_provider(current.provider)
    if command.model is not None and command.model.strip():
        candidate: str | None = command.model
    elif switched and current.model_defaulted:
        candidate = None
    else:
        candidate = current.model
    model, was_defaulted = normalize_phase_model(provider, candidate, defaults)
    return command.model_copy(update={"model": model, "model_defaulted": was_defaulted})
