"""CreateWorkflow handler - thin application service adapter."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from syn_domain.contexts.orchestration.domain.aggregate_workflow_template.WorkflowTemplateAggregate import (
    WorkflowTemplateAggregate,
)

if TYPE_CHECKING:
    from event_sourcing import DomainEvent, EventEnvelope

    from syn_domain.contexts.orchestration.domain.commands.CreateWorkflowTemplateCommand import (
        CreateWorkflowTemplateCommand,
    )
    from syn_domain.contexts.orchestration.domain.commands.UpdateWorkflowTemplateCommand import (
        UpdateWorkflowTemplateCommand,
    )


class WorkflowRepository(Protocol):
    """Repository protocol for Workflow aggregates."""

    async def get_by_id(self, aggregate_id: str) -> WorkflowTemplateAggregate | None:
        """Load an aggregate by ID, or None when the stream does not exist."""
        ...

    async def save(self, aggregate: WorkflowTemplateAggregate) -> None:
        """Save the aggregate and its uncommitted events."""
        ...


class EventPublisher(Protocol):
    """Protocol for publishing domain events."""

    async def publish(self, events: list[EventEnvelope[DomainEvent]]) -> None:
        """Publish domain events for integration.

        Install emits WorkflowTemplateCreated on a new stream and
        WorkflowTemplateUpdated on an existing one (issue #822), so this is
        typed at the base event.
        """
        ...


@dataclass(frozen=True)
class InstallOutcome:
    """Result of an install (issue #822).

    ``changed`` is False when the package was already installed byte-identical
    - same version, same source digest. That is a successful no-op, not a
    conflict, so callers report it as unchanged rather than failing.
    """

    workflow_id: str
    changed: bool


class CreateWorkflowTemplateHandler:
    """Application service handler for CreateWorkflowTemplateCommand.

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

    async def handle(self, command: CreateWorkflowTemplateCommand) -> InstallOutcome:
        """Handle the CreateWorkflowTemplateCommand.

        Install is load-or-create (issue #822). A package declares a stable id,
        so the second install of that package targets an existing stream.
        Constructing a fresh aggregate at version 0 in that case is what
        produced the raw "Concurrency conflict: expected version 0, got 1"
        that reached users.

        Returns:
            The workflow ID and whether anything actually changed.
        """
        aggregate = await self._repository.get_by_id(command.aggregate_id)

        if aggregate is None:
            # First install: create the stream.
            aggregate = WorkflowTemplateAggregate()
            aggregate.create_workflow(command)
        else:
            update_command = _to_update_command(command)
            # Byte-identical reinstall: same version, same digest. Nothing to
            # record, so emit no event at all rather than an Updated carrying
            # the definition already on the stream. Reporting this as success
            # is what makes install idempotent (issue #822), and it is what
            # lets a retry after a partly-failed multi-workflow install get
            # past the workflows that already succeeded.
            if aggregate.is_identical_to(update_command):
                return InstallOutcome(workflow_id=command.aggregate_id, changed=False)

            # Reinstall: replace the definition on the existing stream. The
            # aggregate decides whether this is allowed (version + digest).
            aggregate.update_workflow(update_command)

        # Persist via repository
        await self._repository.save(aggregate)

        # Publish events for integration with other bounded contexts
        events = aggregate.get_uncommitted_events()
        await self._event_publisher.publish(events)  # type: ignore[arg-type]  # generic covariance: list[EventEnvelope[DomainEvent]] compatible with specific event list

        # Clear events after publishing
        aggregate.mark_events_as_committed()

        # Return the new workflow ID
        workflow_id = aggregate.id
        if workflow_id is None:
            msg = "Workflow ID should not be None after creation"
            raise RuntimeError(msg)

        return InstallOutcome(workflow_id=workflow_id, changed=True)


def _to_update_command(
    command: CreateWorkflowTemplateCommand,
) -> UpdateWorkflowTemplateCommand:
    """Translate an install command into the update command for an existing stream.

    Install carries the full definition either way; only the aggregate's
    entry point differs.
    """
    from syn_domain.contexts.orchestration.domain.commands.UpdateWorkflowTemplateCommand import (
        UpdateWorkflowTemplateCommand as _UpdateWorkflowTemplateCommand,
    )

    return _UpdateWorkflowTemplateCommand(
        aggregate_id=command.aggregate_id,
        name=command.name,
        workflow_type=command.workflow_type,
        classification=command.classification,
        repository_url=command.repository_url,
        repository_ref=command.repository_ref,
        phases=command.phases,
        project_name=command.project_name,
        description=command.description,
        input_declarations=command.input_declarations,
        repos=command.repos,
        requires_repos=command.requires_repos,
        claude_plugins=command.claude_plugins,
        skills=command.skills,
        version=command.version,
        source_digest=command.source_digest,
        force=command.force,
    )
