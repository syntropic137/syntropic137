"""CreateWorkflow command - represents intent to create a new workflow."""

from __future__ import annotations

from event_sourcing import command
from pydantic import BaseModel, ConfigDict, Field

# Runtime imports needed for Pydantic model field types (noqa: TC001)
from aef_domain.contexts.orchestration.domain.aggregate_workflow_template.value_objects import (  # noqa: TC001
    PhaseDefinition,
    WorkflowClassification,
    WorkflowType,
)


@command("CreateWorkflowTemplate", "Creates a new workflow with phases")
class CreateWorkflowTemplateCommand(BaseModel):
    """Command to create a new workflow.

    Uses @command decorator for VSA discovery.
    Commands represent intent - what we want to do.
    Named in imperative mood (CreateWorkflow, not WorkflowCreated).
    """

    model_config = ConfigDict(frozen=True)

    # Target aggregate (generated if not provided for new aggregates)
    aggregate_id: str | None = None

    # Required workflow data
    name: str = Field(..., min_length=1, max_length=255)
    workflow_type: WorkflowType
    classification: WorkflowClassification

    # Repository context
    repository_url: str = Field(..., min_length=1)
    repository_ref: str = Field(default="main")

    # Phase definitions
    phases: list[PhaseDefinition] = Field(..., min_length=1)

    # Optional context
    project_name: str | None = None
    description: str | None = None
