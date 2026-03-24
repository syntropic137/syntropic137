"""Workflow aggregate root - shared across workflow slices.

Location: orchestration/domain/aggregate_workflow_template/ (per ADR-020)
"""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from event_sourcing import AggregateRoot, aggregate, command_handler, event_sourcing_handler

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration.domain.aggregate_workflow_template.value_objects import (
        InputDeclaration,
        PhaseDefinition,
    )
    from syn_domain.contexts.orchestration.domain.commands.CreateWorkflowTemplateCommand import (
        CreateWorkflowTemplateCommand,
    )
    from syn_domain.contexts.orchestration.domain.events.WorkflowTemplateCreatedEvent import (
        WorkflowTemplateCreatedEvent,
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
]


def _normalize_event_data(event: Any) -> dict[str, Any]:
    """Extract a flat dict from a typed event or GenericDomainEvent.

    Handles both Pydantic-style events (with attributes) and dict-like
    events from the gRPC event store.
    """
    data = event.model_dump() if hasattr(event, "model_dump") else dict(event)
    # Ensure all expected keys exist
    for field in _EVENT_FIELDS:
        data.setdefault(field, [] if field in ("phases", "input_declarations") else None)
    return data


def _parse_enum(value: Any, enum_type: type) -> Any:
    """Convert a string to an enum, or return as-is if already typed."""
    return enum_type(value) if isinstance(value, str) else value


def _parse_typed_list(raw: list, type_name: str) -> list:
    """Convert a list of dicts to typed objects, or pass through if already typed."""
    from syn_domain.contexts.orchestration.domain.aggregate_workflow_template.value_objects import (
        InputDeclaration,
        PhaseDefinition,
    )

    type_map = {"PhaseDefinition": PhaseDefinition, "InputDeclaration": InputDeclaration}
    cls = type_map[type_name]
    return [cls(**item) if isinstance(item, dict) else item for item in (raw or [])]


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
        self._input_declarations: list[InputDeclaration] = []
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

    @property
    def input_declarations(self) -> list[InputDeclaration]:
        """Get workflow input declarations."""
        return list(self._input_declarations)

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

    @event_sourcing_handler("WorkflowCreated")
    def on_workflow_created_legacy(self, event: WorkflowTemplateCreatedEvent) -> None:
        """Handle legacy 'WorkflowCreated' events stored before the rename.

        Delegates to the canonical handler so old events rehydrate correctly.
        """
        self.on_workflow_created(event)
