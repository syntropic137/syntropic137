"""CreateWorkflow command - represents intent to create a new workflow."""

from __future__ import annotations

from uuid import uuid4

from event_sourcing import command
from pydantic import BaseModel, ConfigDict, Field

# Runtime imports needed for Pydantic model field types (noqa: TC001)
from syn_domain.contexts.orchestration._shared.claude_plugin_ref import (  # noqa: TC001
    ClaudePluginRef,
)
from syn_domain.contexts.orchestration._shared.skill_ref import (  # noqa: TC001
    SkillRef,
)
from syn_domain.contexts.orchestration.domain.aggregate_workflow_template.value_objects import (  # noqa: TC001
    InputDeclaration,
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

    # Target aggregate (auto-generated UUID if not provided)
    aggregate_id: str = Field(default_factory=lambda: str(uuid4()))

    # Required workflow data
    name: str = Field(..., min_length=1, max_length=255)
    workflow_type: WorkflowType
    classification: WorkflowClassification

    # Repository context
    repository_url: str = Field(default="")
    repository_ref: str = Field(default="main")

    # Phase definitions
    phases: list[PhaseDefinition] = Field(..., min_length=1)

    # Optional context
    project_name: str | None = None
    description: str | None = None

    # Input declarations (ISS-211: CC command inputs)
    input_declarations: list[InputDeclaration] = Field(default_factory=list)

    # Multi-repo support (ADR-058)
    repos: list[str] = Field(default_factory=list)
    """Full GitHub URLs for this workflow template. Empty = single-repo (use repository_url)."""

    # Execution gate (ADR-058 #666)
    requires_repos: bool = True
    """Whether this workflow requires repository access at execution time."""

    # Workflow-scope claude plugin refs (issue #726, PR2). Per-phase refs are
    # carried inside ``PhaseDefinition.claude_plugins``; workflow-scope refs
    # apply to every phase and live here so the aggregate carries the full
    # declaration through to execute time.
    claude_plugins: list[ClaudePluginRef] = Field(default_factory=list)

    # Workflow-scope skill refs (issue #772). Additive alongside
    # claude_plugins; per-phase refs are carried inside
    # ``PhaseDefinition.skills``. A follow-up task wires this through the
    # aggregate the same way claude_plugins is wired.
    skills: list[SkillRef] = Field(default_factory=list)
