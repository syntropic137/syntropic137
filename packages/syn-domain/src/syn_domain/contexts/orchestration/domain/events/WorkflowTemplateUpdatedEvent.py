"""WorkflowTemplateUpdated event - an installed definition was replaced.

WHY (issue #822): the stream holds Created -> Updated -> Updated, so replaying
to the position recorded on an execution reconstructs the exact definition that
produced it. That is what makes a stable aggregate ID safe for provenance.
"""

from __future__ import annotations

from event_sourcing import DomainEvent, event
from pydantic import Field

# Runtime imports needed for Pydantic model field types (noqa: TC001)
from syn_domain.contexts.orchestration._shared.event_refs.value_objects import (  # noqa: TC001
    ClaudePluginRef,
    SkillRef,
)
from syn_domain.contexts.orchestration.domain.aggregate_workflow_template.value_objects import (  # noqa: TC001
    InputDeclaration,
    PhaseDefinition,
    WorkflowClassification,
    WorkflowType,
)


@event("WorkflowTemplateUpdated", "v1")
class WorkflowTemplateUpdatedEvent(DomainEvent):
    """Event emitted when an installed workflow template's definition is replaced.

    Carries the full definition rather than a diff, so a single event replays
    to complete state without needing the events before it.
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

    # Multi-repo support (ADR-058)
    repos: list[str] = Field(default_factory=list)

    # Execution gate (ADR-058 #666)
    requires_repos: bool = True

    # Workflow-scope refs (issues #726, #772)
    claude_plugins: list[ClaudePluginRef] = Field(default_factory=list)
    skills: list[SkillRef] = Field(default_factory=list)

    # Provenance (issue #822)
    version: str | None = None
    """Package version this definition came from."""

    source_digest: str | None = None
    """Resolved source commit SHA this definition was built from."""
