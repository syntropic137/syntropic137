"""CreateWorkflow handler - thin application service adapter."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from syn_domain.contexts.orchestration.domain.aggregate_workflow_template.WorkflowTemplateAggregate import (
    WorkflowTemplateAggregate,
)
from syn_shared.agents import normalize_phase_model

if TYPE_CHECKING:
    from event_sourcing import DomainEvent, EventEnvelope

    from syn_domain.contexts.orchestration.domain.aggregate_workflow_template.value_objects import (
        PhaseDefinition,
    )
    from syn_domain.contexts.orchestration.domain.commands.CreateWorkflowTemplateCommand import (
        CreateWorkflowTemplateCommand,
    )
    from syn_domain.contexts.orchestration.domain.commands.UpdateWorkflowTemplateCommand import (
        UpdateWorkflowTemplateCommand,
    )
    from syn_shared.agents import PhaseModelDefaults


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

    It is also THE boundary where a phase that declares no model gets one
    (``model_defaults``). Every template-creating path - the API create route,
    YAML install, offline seeding, the seed scripts - goes through this
    handler, so applying the default here covers all of them. The chosen model
    is written into the command and therefore PERSISTED in the
    WorkflowTemplateCreated/Updated event: changing ``SYN_DEFAULT_*_MODEL``
    later never changes what an existing template replays to. The domain
    itself stays env-free; the caller builds ``model_defaults`` from settings.
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
        defaulted = command.model_copy(
            update={"phases": _with_default_models(command.phases, self._model_defaults)}
        )

        if aggregate is None:
            # First install: create the stream.
            aggregate = WorkflowTemplateAggregate()
            aggregate.create_workflow(defaulted)
        else:
            update_command = _to_update_command(defaulted)
            # Identity is judged against what the PACKAGE declares, using the
            # stored provenance (PhaseDefinition.model_defaulted), not today's
            # setting. Otherwise a byte-identical reinstall after
            # SYN_DEFAULT_*_MODEL changed would look like new content under the
            # same version and be refused as already-installed (issue #822) -
            # while a package that REMOVED a declared model must still count
            # as changed, because only the stored flag can tell them apart.
            as_stored = command.model_copy(
                update={
                    "phases": _as_stored(command.phases, aggregate.phases, self._model_defaults)
                }
            )
            # Byte-identical reinstall: same version, same digest. Nothing to
            # record, so emit no event at all rather than an Updated carrying
            # the definition already on the stream. Reporting this as success
            # is what makes install idempotent (issue #822), and it is what
            # lets a retry after a partly-failed multi-workflow install get
            # past the workflows that already succeeded.
            if aggregate.is_identical_to(_to_update_command(as_stored)):
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


def _with_default_models(
    phases: list[PhaseDefinition], defaults: PhaseModelDefaults
) -> list[PhaseDefinition]:
    """Normalise every phase's model for its provider and record provenance.

    ``normalize_phase_model`` is the same rule execution applies: an unset or
    wrong-provider model (``opus`` on a codex phase, ``gpt-sol`` on a claude
    one) becomes the configured default and is marked ``model_defaulted``; a
    usable declared model is kept and marked declared. A caller cannot set the
    flag - it is overwritten here either way.
    """
    normalised: list[PhaseDefinition] = []
    for phase in phases:
        model, was_defaulted = normalize_phase_model(phase.provider, phase.model, defaults)
        normalised.append(
            phase.model_copy(update={"model": model, "model_defaulted": was_defaulted})
        )
    return normalised


def _as_stored(
    phases: list[PhaseDefinition],
    stored: list[PhaseDefinition],
    defaults: PhaseModelDefaults,
) -> list[PhaseDefinition]:
    """The incoming phases as they would look if nothing had changed.

    A phase whose model the package does not usably declare takes the stored
    phase's model ONLY when that stored model was itself a default
    (``model_defaulted``). Everything else is compared as declared:

    - undeclared now, defaulted before      -> identical (settings may differ)
    - undeclared now, DECLARED before       -> differs: the package removed it
    - undeclared now, legacy ``None`` before -> identical (both undeclared)
    - declared now                          -> compared as declared
    """
    stored_by_id = {phase.phase_id: phase for phase in stored}
    result: list[PhaseDefinition] = []
    for phase in phases:
        _, needs_default = normalize_phase_model(phase.provider, phase.model, defaults)
        previous = stored_by_id.get(phase.phase_id)
        if needs_default and previous is not None and previous.model_defaulted:
            result.append(
                phase.model_copy(update={"model": previous.model, "model_defaulted": True})
            )
        else:
            result.append(phase.model_copy(update={"model_defaulted": False}))
    return result


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
