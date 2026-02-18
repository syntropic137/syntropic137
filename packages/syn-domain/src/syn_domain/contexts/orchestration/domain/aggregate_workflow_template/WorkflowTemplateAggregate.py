"""Workflow aggregate root - shared across workflow slices.

Location: orchestration/domain/aggregate_workflow_template/ (per ADR-020)
"""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING
from uuid import uuid4

from event_sourcing import AggregateRoot, aggregate, command_handler, event_sourcing_handler

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration.domain.aggregate_workflow_template.value_objects import (
        PhaseDefinition,
    )
    from syn_domain.contexts.orchestration.domain.commands.CreateWorkflowTemplateCommand import (
        CreateWorkflowTemplateCommand,
    )
    from syn_domain.contexts.orchestration.domain.events.WorkflowTemplateCreatedEvent import (
        WorkflowTemplateCreatedEvent,
    )


class WorkflowStatus(str, Enum):
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
        self._status: WorkflowStatus = WorkflowStatus.PENDING
        self._project_name: str | None = None
        self._description: str | None = None

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
        from syn_domain.contexts.orchestration.domain.aggregate_workflow_template.value_objects import (
            PhaseDefinition,
            WorkflowClassification,
            WorkflowType,
        )

        # Handle both typed events and GenericDomainEvent (dict-based)
        if hasattr(event, "model_dump"):
            # It's a typed event, use attributes directly
            self._name = event.name
            workflow_type = event.workflow_type
            classification = event.classification
            phases_raw = event.phases
        else:
            # It's a GenericDomainEvent or dict-like object
            event_data = event.model_dump() if hasattr(event, "model_dump") else dict(event)
            self._name = event_data.get("name")
            workflow_type = event_data.get("workflow_type")  # type: ignore[assignment]
            classification = event_data.get("classification")  # type: ignore[assignment]
            phases_raw = event_data.get("phases", [])

        # Convert workflow_type to enum if it's a string
        if isinstance(workflow_type, str):
            self._workflow_type = WorkflowType(workflow_type)
        else:
            self._workflow_type = workflow_type

        # Convert classification to enum if it's a string
        if isinstance(classification, str):
            self._classification = WorkflowClassification(classification)
        else:
            self._classification = classification

        # Handle repository URL and ref
        if hasattr(event, "repository_url"):
            self._repository_url = event.repository_url
            self._repository_ref = event.repository_ref
        else:
            event_data = event.model_dump() if hasattr(event, "model_dump") else dict(event)
            self._repository_url = event_data.get("repository_url")
            self._repository_ref = event_data.get("repository_ref")

        # Convert phases - they may be dicts or PhaseDefinition objects
        self._phases = []
        for phase in phases_raw:
            if isinstance(phase, dict):
                self._phases.append(PhaseDefinition(**phase))
            else:
                self._phases.append(phase)

        self._status = WorkflowStatus.PENDING

        # Handle optional fields
        if hasattr(event, "project_name"):
            self._project_name = event.project_name
            self._description = event.description
        else:
            event_data = event.model_dump() if hasattr(event, "model_dump") else dict(event)
            self._project_name = event_data.get("project_name")
            self._description = event_data.get("description")

    @event_sourcing_handler("WorkflowCreated")
    def on_workflow_created_legacy(self, event: WorkflowTemplateCreatedEvent) -> None:
        """Handle legacy 'WorkflowCreated' events stored before the rename.

        Delegates to the canonical handler so old events rehydrate correctly.
        """
        self.on_workflow_created(event)
