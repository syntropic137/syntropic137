"""Value objects for the workflows bounded context."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from syn_domain.contexts.orchestration._shared.claude_plugin_ref import (
    ClaudePluginRef,  # noqa: TC001 - needed at runtime for Pydantic field validation
)
from syn_domain.contexts.orchestration._shared.skill_ref import (
    SkillRef,  # noqa: TC001 - needed at runtime for Pydantic field validation
)


class WorkflowType(StrEnum):
    """Type of workflow execution."""

    RESEARCH = "research"
    PLANNING = "planning"
    IMPLEMENTATION = "implementation"
    REVIEW = "review"
    DEPLOYMENT = "deployment"
    CUSTOM = "custom"


class WorkflowClassification(StrEnum):
    """Classification of workflow complexity."""

    SIMPLE = "simple"
    STANDARD = "standard"
    COMPLEX = "complex"
    EPIC = "epic"


class PhaseExecutionType(StrEnum):
    """How a phase should be executed."""

    SEQUENTIAL = "sequential"
    PARALLEL = "parallel"
    HUMAN_IN_LOOP = "human_in_loop"


class InputDeclaration(BaseModel):
    """Declaration of an expected workflow input.

    Describes what data a workflow expects at execution time.
    Used for validation, documentation, and UI form generation.
    """

    model_config = ConfigDict(frozen=True)

    name: str = Field(..., min_length=1)
    description: str | None = None
    required: bool = True
    default: str | None = None


class PhaseDefinition(BaseModel):
    """Definition of a workflow phase.

    Phases are the building blocks of workflows.
    Each phase has inputs, outputs, and execution parameters.

    The ``prompt_template`` field contains the resolved prompt text.
    When a workflow YAML uses ``prompt_file`` to reference an external
    ``.md`` file, the loader resolves it into ``prompt_template`` before
    the domain model is constructed (see ``WorkflowDefinition.from_file``).
    """

    model_config = ConfigDict(frozen=True)

    # Identity
    phase_id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1, max_length=255)
    order: int = Field(..., ge=1)

    # Execution
    execution_type: PhaseExecutionType = PhaseExecutionType.SEQUENTIAL

    # Description
    description: str | None = None

    # Input/Output definitions
    input_artifact_types: list[str] = Field(default_factory=list)
    output_artifact_types: list[str] = Field(default_factory=list)

    # Agent configuration
    prompt_template: str | None = None
    """The resolved prompt template content for this phase.

    This may originate from an inline ``prompt_template`` in the workflow
    YAML or from an external ``.md`` file referenced via ``prompt_file``.
    In either case, the value stored here is the final prompt text.
    """

    max_tokens: int | None = None
    timeout_seconds: int | None = None
    allowed_tools: list[str] = Field(default_factory=list)
    """Tools allowed during this phase execution."""

    # Claude Code command extensions (ISS-211)
    argument_hint: str | None = None
    """Describes what $ARGUMENTS expects for this phase (e.g., '[task-description]')."""

    model: str | None = None
    """Per-phase model override (e.g., 'sonnet', 'opus')."""

    provider: str | None = None
    """Per-phase agent provider override ('claude' or 'codex').

    None means the execution default ('claude', the ``claude -p`` docker
    path). 'codex' routes the phase through the programmatic ``codex exec``
    harness on the same docker path. Sourced from the workflow YAML
    ``agent.provider`` field.
    """

    allow_delegation: bool = False
    """When true, both agent auths are staged so the phase's primary agent can
    delegate one-shot to the other CLI. Headless providers only. Sourced from
    the workflow YAML ``agent.allow_delegation`` field."""

    # Workflow-author-declared plugin refs at phase scope (issue #726). PR1 carries
    # them through the YAML to the domain; PR2's resolution service rewrites them
    # into ResolvedClaudePlugin entries on ExecutablePhase.
    claude_plugins: tuple[ClaudePluginRef, ...] = Field(default_factory=tuple)
    # Workflow-author-declared skill refs at phase scope (issue #772). Additive
    # alongside claude_plugins; carried through the YAML to the domain. A
    # follow-up resolution service rewrites them into ResolvedSkill entries
    # on ExecutablePhase.
    skills: tuple[SkillRef, ...] = Field(default_factory=tuple)
