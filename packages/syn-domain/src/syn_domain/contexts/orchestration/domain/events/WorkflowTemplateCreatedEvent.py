"""WorkflowCreated event - represents the fact that a workflow was created."""

from __future__ import annotations

from event_sourcing import DomainEvent, event
from pydantic import Field  # noqa: TC002 — needed at runtime for default_factory

# Runtime imports needed for Pydantic model field types (noqa: TC001)
from syn_domain.contexts.orchestration.domain.aggregate_workflow_template.value_objects import (  # noqa: TC001
    InputDeclaration,
    PhaseDefinition,
    WorkflowClassification,
    WorkflowType,
)


@event("WorkflowTemplateCreated", "v1")
class WorkflowTemplateCreatedEvent(DomainEvent):
    """Event emitted when a workflow is created.

    Extends DomainEvent from event_sourcing SDK.
    Events represent facts - what happened.
    Named in past tense (WorkflowCreated, not CreateWorkflow).

    DomainEvent provides:
    - Immutability (frozen=True)
    - JSON serialization
    - event_type and schema_version via @event decorator
    """

    # Workflow identity
    workflow_id: str

    # Workflow data
    name: str
    workflow_type: WorkflowType
    classification: WorkflowClassification

    # Repository context
    repository_url: str
    repository_ref: str

    # Phase definitions
    phases: list[PhaseDefinition]

    # Optional context
    project_name: str | None = None
    description: str | None = None

    # Input declarations (ISS-211)
    input_declarations: list[InputDeclaration] = Field(default_factory=list)
