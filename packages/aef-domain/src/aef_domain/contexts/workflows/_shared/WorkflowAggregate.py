"""Workflow aggregate root - shared across workflow slices."""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING
from uuid import uuid4

from event_sourcing import AggregateRoot, aggregate, command_handler, event_sourcing_handler

if TYPE_CHECKING:
    from aef_domain.contexts.workflows._shared.value_objects import PhaseDefinition
    from aef_domain.contexts.workflows.create_workflow.CreateWorkflowCommand import (
        CreateWorkflowCommand,
    )
    from aef_domain.contexts.workflows.create_workflow.WorkflowCreatedEvent import (
        WorkflowCreatedEvent,
    )


class WorkflowStatus(str, Enum):
    """Status of a workflow."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@aggregate("Workflow")
class WorkflowAggregate(AggregateRoot["WorkflowCreatedEvent"]):
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

    @command_handler("CreateWorkflowCommand")
    def create_workflow(self, command: CreateWorkflowCommand) -> None:
        """Handle CreateWorkflowCommand.

        Validates business rules and emits WorkflowCreatedEvent.
        """
        # Import here to avoid circular imports at module level
        from aef_domain.contexts.workflows.create_workflow.WorkflowCreatedEvent import (
            WorkflowCreatedEvent,
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
        event = WorkflowCreatedEvent(
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

    @event_sourcing_handler("WorkflowCreated")
    def on_workflow_created(self, event: WorkflowCreatedEvent) -> None:
        """Apply WorkflowCreatedEvent to update aggregate state.

        Event handlers update state only - NO business logic.
        Must be idempotent for rehydration.
        """
        self._name = event.name
        self._workflow_type = event.workflow_type
        self._classification = event.classification
        self._repository_url = event.repository_url
        self._repository_ref = event.repository_ref
        self._phases = list(event.phases)
        self._status = WorkflowStatus.PENDING
        self._project_name = event.project_name
        self._description = event.description
