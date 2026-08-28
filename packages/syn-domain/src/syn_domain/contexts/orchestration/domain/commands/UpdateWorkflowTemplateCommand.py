"""UpdateWorkflowTemplate command - intent to replace an installed definition.

WHY (issue #822): reinstalling a package is the normal update path. The
aggregate ID is the package's stable id, so a second install has to update the
existing stream rather than construct a fresh aggregate at version 0.
"""

from __future__ import annotations

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


@command("UpdateWorkflowTemplate", "Replaces the definition of an installed workflow")
class UpdateWorkflowTemplateCommand(BaseModel):
    """Command to replace an installed workflow template's definition.

    Carries the full definition, not a patch: an install replaces what the
    package declares wholesale, so a phase removed from the package is removed
    from the template.
    """

    model_config = ConfigDict(frozen=True)

    # Target aggregate (the package's stable id - never generated here)
    aggregate_id: str = Field(..., min_length=1)

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

    # Input declarations (ISS-211)
    input_declarations: list[InputDeclaration] = Field(default_factory=list)

    # Multi-repo support (ADR-058)
    repos: list[str] = Field(default_factory=list)

    # Execution gate (ADR-058 #666)
    requires_repos: bool = True

    # Workflow-scope refs (issues #726, #772)
    claude_plugins: list[ClaudePluginRef] = Field(default_factory=list)
    skills: list[SkillRef] = Field(default_factory=list)

    # Provenance (issue #822)
    version: str | None = None
    """Package version being installed. Compared against the installed version."""

    source_digest: str | None = None
    """Resolved source commit SHA. Same version + different digest is refused."""

    force: bool = False
    """Explicit intent to overwrite. Required to reinstall a matching version."""
