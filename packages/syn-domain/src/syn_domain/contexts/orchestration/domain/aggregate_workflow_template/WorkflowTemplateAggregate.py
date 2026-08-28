"""Workflow aggregate root - shared across workflow slices.

Location: orchestration/domain/aggregate_workflow_template/ (per ADR-020)
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from event_sourcing import (
    AggregateRoot,
    DomainEvent,
    aggregate,
    command_handler,
    event_sourcing_handler,
)

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration._shared.claude_plugin_ref import (
        ClaudePluginRef,
    )
    from syn_domain.contexts.orchestration._shared.skill_ref import (
        SkillRef,
    )
    from syn_domain.contexts.orchestration.domain.aggregate_workflow_template.value_objects import (
        InputDeclaration,
        PhaseDefinition,
    )
    from syn_domain.contexts.orchestration.domain.commands.ArchiveWorkflowTemplateCommand import (
        ArchiveWorkflowTemplateCommand,
    )
    from syn_domain.contexts.orchestration.domain.commands.CreateWorkflowTemplateCommand import (
        CreateWorkflowTemplateCommand,
    )
    from syn_domain.contexts.orchestration.domain.commands.UpdatePhasePromptCommand import (
        UpdatePhasePromptCommand,
    )
    from syn_domain.contexts.orchestration.domain.commands.UpdateWorkflowTemplateCommand import (
        UpdateWorkflowTemplateCommand,
    )
    from syn_domain.contexts.orchestration.domain.events.WorkflowPhaseUpdatedEvent import (
        WorkflowPhaseUpdatedEvent,
    )
    from syn_domain.contexts.orchestration.domain.events.WorkflowTemplateArchivedEvent import (
        WorkflowTemplateArchivedEvent,
    )
    from syn_domain.contexts.orchestration.domain.events.WorkflowTemplateCreatedEvent import (
        WorkflowTemplateCreatedEvent,
    )
    from syn_domain.contexts.orchestration.domain.events.WorkflowTemplateUpdatedEvent import (
        WorkflowTemplateUpdatedEvent,
    )


_EVENT_FIELDS = [
    "name",
    "workflow_type",
    "classification",
    "repository_url",
    "repository_ref",
    "phases",
    "project_name",
    "description",
    "input_declarations",
    "claude_plugins",
    "skills",
    "version",
    "source_digest",
]


def _normalize_event_data(event: DomainEvent) -> dict[str, Any]:
    """Extract a flat dict from a typed event or GenericDomainEvent.

    Handles both Pydantic-style events (with attributes) and dict-like
    events from the gRPC event store.
    """
    data = event.model_dump() if hasattr(event, "model_dump") else dict(event)
    # Ensure all expected keys exist
    for field in _EVENT_FIELDS:
        data.setdefault(
            field,
            [] if field in ("phases", "input_declarations", "claude_plugins", "skills") else None,
        )
    return data


def _parse_enum(value: str | StrEnum, enum_type: type[StrEnum]) -> StrEnum:
    """Convert a string to an enum, or return as-is if already typed."""
    return enum_type(value) if isinstance(value, str) else value


_PHASE_UPDATE_FIELDS = [
    "workflow_id",
    "phase_id",
    "prompt_template",
    "model",
    "provider",
    "timeout_seconds",
    "allowed_tools",
]


def _normalize_phase_update_data(event: DomainEvent) -> dict[str, Any]:
    """Extract a flat dict from a WorkflowPhaseUpdated event.

    Handles both Pydantic-style events and dict-like events from gRPC.
    """
    data = event.model_dump() if hasattr(event, "model_dump") else dict(event)
    for field in _PHASE_UPDATE_FIELDS:
        data.setdefault(field, None)
    return data


def _coalesce[T](new: T | None, existing: T) -> T:
    """Return new if not None, else existing."""
    return new if new is not None else existing


def _apply_phase_update(phase: PhaseDefinition, data: dict[str, Any]) -> PhaseDefinition:
    """Create a new PhaseDefinition with updated fields from event data."""
    from syn_domain.contexts.orchestration.domain.aggregate_workflow_template.value_objects import (
        PhaseDefinition,
    )

    updated_provider = _coalesce(data["provider"], phase.provider)
    return PhaseDefinition(
        phase_id=phase.phase_id,
        name=phase.name,
        order=phase.order,
        execution_type=phase.execution_type,
        description=phase.description,
        input_artifact_types=phase.input_artifact_types,
        output_artifact_types=phase.output_artifact_types,
        prompt_template=data["prompt_template"],
        max_tokens=phase.max_tokens,
        timeout_seconds=_coalesce(data["timeout_seconds"], phase.timeout_seconds),
        allowed_tools=_coalesce(data["allowed_tools"], list(phase.allowed_tools)),
        argument_hint=phase.argument_hint,
        model=_coalesce(data["model"], phase.model),
        provider=updated_provider,
        allow_delegation=phase.allow_delegation,
        skills=phase.skills,
        claude_plugins=phase.claude_plugins,
    )


def _parse_typed_list(raw: list, type_name: str) -> list:
    """Convert a list of dicts to typed objects, or pass through if already typed."""
    from syn_domain.contexts.orchestration.domain.aggregate_workflow_template.value_objects import (
        InputDeclaration,
        PhaseDefinition,
    )

    type_map = {"PhaseDefinition": PhaseDefinition, "InputDeclaration": InputDeclaration}
    cls = type_map[type_name]
    return [cls(**item) if isinstance(item, dict) else item for item in (raw or [])]


class WorkflowStatus(StrEnum):
    """Status of a workflow."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@aggregate("WorkflowTemplate")
class WorkflowTemplateAggregate(AggregateRoot["WorkflowTemplateCreatedEvent"]):
    """Workflow aggregate root.

    Manages the lifecycle of a workflow from creation through completion.
    Uses event sourcing to track all state changes.

    Command handlers validate business rules and emit events.
    Event handlers update state (pure, no side effects).
    """

    # Type hint for decorator-set attribute (set by @aggregate)
    _aggregate_type: str

    def __init__(self) -> None:
        super().__init__()
        self._name: str | None = None
        self._workflow_type: str | None = None
        self._classification: str | None = None
        self._repository_url: str | None = None
        self._repository_ref: str | None = None
        self._phases: list[PhaseDefinition] = []
        self._input_declarations: list[InputDeclaration] = []
        self._repos: list[str] = []
        self._status: WorkflowStatus = WorkflowStatus.PENDING
        self._project_name: str | None = None
        self._description: str | None = None
        self._is_archived: bool = False
        self._requires_repos: bool = True
        # WHY (issue #726, PR2): workflow-scope claude_plugin refs are
        # part of the aggregate's identity at execute time so the resolver
        # can union them with per-phase refs without re-reading YAML.
        self._claude_plugins: list[ClaudePluginRef] = []
        # WHY (issue #772): workflow-scope skill refs mirror claude_plugins so
        # the skill resolution service can union them with per-phase refs at
        # execute time without re-reading YAML.
        self._skills: list[SkillRef] = []
        # WHY (issue #822): provenance for install/upsert. version drives the
        # already-installed refusal; source_digest catches a republished
        # version whose content changed underneath the same version string.
        self._package_version: str | None = None
        self._source_digest: str | None = None

    def get_aggregate_type(self) -> str:
        """Return aggregate type name."""
        return self._aggregate_type  # Set by @aggregate decorator

    @property
    def name(self) -> str | None:
        """Get workflow name."""
        return self._name

    @property
    def status(self) -> WorkflowStatus:
        """Get workflow status."""
        return self._status

    @property
    def phases(self) -> list[PhaseDefinition]:
        """Get workflow phases."""
        return list(self._phases)

    @property
    def is_archived(self) -> bool:
        """Whether this workflow template has been archived."""
        return self._is_archived

    @property
    def input_declarations(self) -> list[InputDeclaration]:
        """Get workflow input declarations."""
        return list(self._input_declarations)

    @property
    def requires_repos(self) -> bool:
        """Whether this workflow requires repository access at execution time (ADR-058 #666)."""
        return self._requires_repos

    @property
    def repos(self) -> list[str]:
        """Get template-level GitHub URLs for workspace hydration (ADR-058)."""
        return list(self._repos)

    @property
    def claude_plugins(self) -> list[ClaudePluginRef]:
        """Get workflow-scope claude plugin refs (issue #726).

        Per-phase refs live on each ``PhaseDefinition.claude_plugins``;
        this list applies to every phase via the resolution service union.
        """
        return list(self._claude_plugins)

    @property
    def skills(self) -> list[SkillRef]:
        """Get workflow-scope skill refs (issue #772).

        Per-phase refs live on each ``PhaseDefinition.skills``; this list
        applies to every phase via the skill resolution service union.
        """
        return list(self._skills)

    @property
    def package_version(self) -> str | None:
        """Package version of the installed definition (issue #822).

        Distinct from ``version``, which the SDK owns as the aggregate's
        stream position. The package version is what a human reads; the
        stream position is what replays to the exact definition. Recording
        both on WorkflowExecutionStarted is follow-up work, not done here.
        """
        return self._package_version

    @property
    def source_digest(self) -> str | None:
        """Resolved source commit SHA of the installed definition (issue #822)."""
        return self._source_digest

    # =========================================================================
    # COMMAND HANDLERS - Validate business rules, emit events
    # =========================================================================

    @command_handler("CreateWorkflowTemplateCommand")
    def create_workflow(self, command: CreateWorkflowTemplateCommand) -> None:
        """Handle CreateWorkflowTemplateCommand.

        Validates business rules and emits WorkflowTemplateCreatedEvent.
        """
        # Import here to avoid circular imports at module level
        from syn_domain.contexts.orchestration.domain.events.WorkflowTemplateCreatedEvent import (
            WorkflowTemplateCreatedEvent,
        )

        # Validate: workflow must not already exist
        if self.id is not None:
            msg = "Workflow already exists"
            raise ValueError(msg)

        # Validate: must have at least one phase
        if not command.phases:
            msg = "Workflow must have at least one phase"
            raise ValueError(msg)

        # Generate ID if not provided
        workflow_id = command.aggregate_id or str(uuid4())

        # Initialize aggregate
        self._initialize(workflow_id)

        # Create and apply the event
        event = WorkflowTemplateCreatedEvent(
            workflow_id=workflow_id,
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
        )

        self._apply(event)

    def _guard_provenance_retained(self, command: UpdateWorkflowTemplateCommand) -> None:
        """Refuse an install that would erase provenance already recorded.

        Without this the digest guard is bypassed by simply declaring nothing:
        the matching-version check does not fire, the update is accepted, and
        version and digest are overwritten with None, so a republished package
        installs cleanly afterwards.

        ``force`` does not bypass this. Force means "overwrite this version on
        purpose", not "drop the evidence".
        """
        from syn_domain.contexts.orchestration.domain.aggregate_workflow_template.errors import (
            WorkflowTemplateProvenanceStrippedError,
        )

        if self._package_version is not None and command.version is None:
            raise WorkflowTemplateProvenanceStrippedError(
                workflow_id=str(self.id),
                field="version",
                installed_value=self._package_version,
            )
        if self._source_digest is not None and command.source_digest is None:
            raise WorkflowTemplateProvenanceStrippedError(
                workflow_id=str(self.id),
                field="source digest",
                installed_value=self._source_digest,
            )

    def _definition_fingerprint(self) -> tuple[object, ...]:
        """Every persisted field of the current definition, in a fixed order.

        Paired with ``_command_fingerprint``. Comparing tuples rather than
        chaining a dozen ``and`` clauses keeps this within the complexity
        budget and makes a forgotten field a visible asymmetry between the
        two methods rather than a silently dropped comparison.
        """
        return (
            self._name,
            self._workflow_type,
            self._classification,
            self._repository_url,
            self._repository_ref,
            self._project_name,
            self._description,
            self._requires_repos,
            self._phases,
            self._input_declarations,
            self._repos,
            self._claude_plugins,
            self._skills,
            self._package_version,
            self._source_digest,
        )

    @staticmethod
    def _command_fingerprint(command: UpdateWorkflowTemplateCommand) -> tuple[object, ...]:
        """The same fields as ``_definition_fingerprint``, from the command."""
        return (
            command.name,
            command.workflow_type,
            command.classification,
            command.repository_url,
            command.repository_ref,
            command.project_name,
            command.description,
            command.requires_repos,
            list(command.phases),
            list(command.input_declarations),
            [str(r) for r in command.repos],
            list(command.claude_plugins),
            list(command.skills),
            command.version,
            command.source_digest,
        )

    def is_identical_to(self, command: UpdateWorkflowTemplateCommand) -> bool:
        """Whether applying this command would change nothing at all.

        Identity is decided from the aggregate's OWN state, never from the
        caller's claimed digest (issue #822). ``source_digest`` is provenance:
        it says which commit the package came from, and the server cannot
        verify it. Using it as the equality proof let a caller submit
        materially different content under a digest it had used before and
        have the server accept it as unchanged without ever looking.

        The aggregate must also be ACTIVE. An archived template whose stored
        definition still matches is not "already installed": reinstalling it
        has to reactivate it, which only a full-definition event does.
        """
        if self._is_archived:
            return False
        return self._definition_fingerprint() == self._command_fingerprint(command)

    def _guard_version_not_already_installed(self, command: UpdateWorkflowTemplateCommand) -> None:
        """Refuse a reinstall of a version already installed, unless forced.

        A matching version whose source digest differs is refused with the
        stronger error: that is the signature of a republished version, which
        a version check alone would not catch.

        A byte-identical reinstall never reaches here: the caller treats it as
        a no-op, because #822 is about install being idempotent and failing on
        an identical reinstall is not idempotent.
        """
        from syn_domain.contexts.orchestration.domain.aggregate_workflow_template.errors import (
            WorkflowTemplateDigestMismatchError,
            WorkflowTemplateVersionAlreadyInstalledError,
        )

        if command.version is None or command.version != self._package_version:
            return
        if command.force:
            return
        # An archived template is not "already installed". Reinstalling it is
        # how a user restores one a failed update archived, so refusing here
        # would strand them behind --force for an ordinary recovery.
        if self._is_archived:
            return

        digest_changed = (
            command.source_digest is not None
            and self._source_digest is not None
            and command.source_digest != self._source_digest
        )
        if digest_changed:
            raise WorkflowTemplateDigestMismatchError(
                workflow_id=str(self.id),
                version=str(command.version),
                installed_digest=str(self._source_digest),
                incoming_digest=str(command.source_digest),
            )

        raise WorkflowTemplateVersionAlreadyInstalledError(
            workflow_id=str(self.id),
            version=str(command.version),
        )

    @command_handler("UpdateWorkflowTemplateCommand")
    def update_workflow(self, command: UpdateWorkflowTemplateCommand) -> None:
        """Handle UpdateWorkflowTemplateCommand.

        Replaces an installed definition wholesale. This is the second and
        subsequent install of the same package id (issue #822).
        """
        from syn_domain.contexts.orchestration.domain.events.WorkflowTemplateUpdatedEvent import (
            WorkflowTemplateUpdatedEvent,
        )

        # Guard: workflow must already exist
        if self.id is None:
            msg = "Workflow does not exist"
            raise ValueError(msg)

        # Guard: must have at least one phase
        if not command.phases:
            msg = "Workflow must have at least one phase"
            raise ValueError(msg)

        self._guard_provenance_retained(command)
        self._guard_version_not_already_installed(command)

        event = WorkflowTemplateUpdatedEvent(
            workflow_id=self.id,
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
        )

        self._apply(event)

    @command_handler("UpdatePhasePromptCommand")
    def update_phase_prompt(self, command: UpdatePhasePromptCommand) -> None:
        """Handle UpdatePhasePromptCommand.

        Validates business rules and emits WorkflowPhaseUpdatedEvent.
        """
        from syn_domain.contexts.orchestration.domain.events.WorkflowPhaseUpdatedEvent import (
            WorkflowPhaseUpdatedEvent,
        )

        # Guard: workflow must already exist
        if self.id is None:
            msg = "Workflow does not exist"
            raise ValueError(msg)

        # Guard: phase_id must exist in current phases
        phase_ids = {p.phase_id for p in self._phases}
        if command.phase_id not in phase_ids:
            msg = f"Phase '{command.phase_id}' not found in workflow"
            raise ValueError(msg)

        event = WorkflowPhaseUpdatedEvent(
            workflow_id=self.id,
            phase_id=command.phase_id,
            prompt_template=command.prompt_template,
            model=command.model,
            provider=command.provider,
            timeout_seconds=command.timeout_seconds,
            allowed_tools=command.allowed_tools,
        )

        self._apply(event)

    # =========================================================================
    # EVENT SOURCING HANDLERS - Update state only, NO business logic
    # =========================================================================

    @event_sourcing_handler("WorkflowTemplateCreated")
    def on_workflow_created(self, event: WorkflowTemplateCreatedEvent) -> None:
        """Apply WorkflowTemplateCreatedEvent to update aggregate state.

        Event handlers update state only - NO business logic.
        Must be idempotent for rehydration.

        Note: When rehydrating from gRPC event store, event may be a GenericDomainEvent
        with dict attributes instead of proper typed objects. Handle both cases.
        """
        self._apply_definition(event)

    @event_sourcing_handler("WorkflowTemplateUpdated")
    def on_workflow_updated(self, event: WorkflowTemplateUpdatedEvent) -> None:
        """Apply WorkflowTemplateUpdatedEvent to update aggregate state.

        WHY (issue #822): the updated event carries the full definition, so
        applying it is the same state transition as create. Reinstalling also
        clears the archived flag, which is what makes `install` able to bring
        back a template a failed `update` had archived.
        """
        self._apply_definition(event)

    def _apply_definition(self, event: DomainEvent) -> None:
        """Apply a full workflow definition event to aggregate state.

        Shared by the created and updated handlers - both events carry the
        complete definition, so both replay through the same transition.
        """
        data = _normalize_event_data(event)

        from syn_domain.contexts.orchestration.domain.aggregate_workflow_template.value_objects import (
            WorkflowClassification,
            WorkflowType,
        )

        self._name = data["name"]
        self._workflow_type = _parse_enum(data["workflow_type"], WorkflowType)
        self._classification = _parse_enum(data["classification"], WorkflowClassification)
        self._repository_url = data["repository_url"]
        self._repository_ref = data["repository_ref"]
        self._phases = _parse_typed_list(data["phases"], "PhaseDefinition")
        self._status = WorkflowStatus.PENDING
        self._project_name = data["project_name"]
        self._description = data["description"]
        self._input_declarations = _parse_typed_list(data["input_declarations"], "InputDeclaration")
        self._repos = [str(r) for r in data.get("repos", [])]
        self._requires_repos = bool(data.get("requires_repos", True))
        # WHY (issue #726): legacy events have no claude_plugins field; coerce
        # raw dicts (gRPC GenericDomainEvent) into ClaudePluginRef instances so
        # the aggregate exposes the same typed list whether it just emitted the
        # event or rehydrated from an older one.
        from syn_domain.contexts.orchestration._shared.claude_plugin_ref import (
            ClaudePluginRef,
        )

        raw_plugins = data.get("claude_plugins") or []
        self._claude_plugins = [
            item if isinstance(item, ClaudePluginRef) else ClaudePluginRef.model_validate(item)
            for item in raw_plugins
        ]

        # WHY (issue #772): mirrors the claude_plugins coercion above; legacy
        # events have no skills field.
        from syn_domain.contexts.orchestration._shared.skill_ref import SkillRef

        raw_skills = data.get("skills") or []
        self._skills = [
            item if isinstance(item, SkillRef) else SkillRef.model_validate(item)
            for item in raw_skills
        ]

        # WHY (issue #822): legacy events predate provenance; absent stays None
        # so an install carrying a version is never mistaken for a reinstall.
        self._package_version = data.get("version")
        self._source_digest = data.get("source_digest")

        # A full definition event reactivates the template. Applying this in
        # the shared path rather than only on Updated keeps archive semantics
        # consistent across legacy WorkflowCreated, WorkflowTemplateCreated and
        # WorkflowTemplateUpdated, so a stream ending in any of them replays to
        # active rather than depending on which one it happens to end with.
        self._is_archived = False

    @command_handler("ArchiveWorkflowTemplateCommand")
    def archive_workflow(self, command: ArchiveWorkflowTemplateCommand) -> None:
        """Handle ArchiveWorkflowTemplateCommand.

        Guards against double-archive. The active-execution guard is
        handled by the application service (cross-aggregate concern).
        """
        from syn_domain.contexts.orchestration.domain.events.WorkflowTemplateArchivedEvent import (
            WorkflowTemplateArchivedEvent,
        )

        if self._is_archived:
            msg = "Workflow template already archived"
            raise ValueError(msg)

        event = WorkflowTemplateArchivedEvent(
            workflow_id=str(self.id),
            archived_by=command.archived_by,
        )
        self._apply(event)

    @event_sourcing_handler("WorkflowTemplateArchived")
    def on_workflow_archived(self, _event: WorkflowTemplateArchivedEvent) -> None:
        """Apply WorkflowTemplateArchivedEvent to update aggregate state."""
        self._is_archived = True

    @event_sourcing_handler("WorkflowCreated")
    def on_workflow_created_legacy(self, event: WorkflowTemplateCreatedEvent) -> None:
        """Handle legacy 'WorkflowCreated' events stored before the rename.

        Delegates to the canonical handler so old events rehydrate correctly.
        """
        self.on_workflow_created(event)

    @event_sourcing_handler("WorkflowPhaseUpdated")
    def on_phase_updated(self, event: WorkflowPhaseUpdatedEvent) -> None:
        """Apply WorkflowPhaseUpdatedEvent to update a phase in aggregate state.

        Rebuilds the phases list with the updated phase.
        Must be idempotent for rehydration.
        """
        data = _normalize_phase_update_data(event)
        phase_id = data["phase_id"]
        self._phases = [
            _apply_phase_update(p, data) if p.phase_id == phase_id else p for p in self._phases
        ]
