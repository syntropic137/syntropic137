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
from syn_shared.agents import DEFAULT_PHASE_SANDBOX
from syn_shared.platform_access import PlatformScope


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


#: The members an executor actually implements. `parallel` has no parallel
#: processor and `human_in_loop` has no approval gate; nothing in the codebase
#: branches on this field at all, so every phase runs sequentially whatever it
#: declares. Kept as a named set rather than inlined so the authoring check and
#: the execution check cannot drift apart.
IMPLEMENTED_EXECUTION_TYPES: frozenset[PhaseExecutionType] = frozenset(
    {PhaseExecutionType.SEQUENTIAL}
)


class UnsupportedExecutionTypeError(ValueError):
    """A phase declared an execution type no executor implements."""

    def __init__(self, execution_type: object, *, phase_id: str | None = None) -> None:
        where = f"Phase '{phase_id}': " if phase_id else ""
        supported = ", ".join(sorted(t.value for t in IMPLEMENTED_EXECUTION_TYPES))
        super().__init__(
            f"{where}execution_type '{execution_type}' is not implemented: every "
            f"phase runs sequentially, so this value has never changed how a "
            f"phase runs. Remove it, or use one of: {supported}."
        )


def require_supported_execution_type(
    execution_type: object,
    *,
    phase_id: str | None = None,
) -> PhaseExecutionType:
    """Return the execution type, or raise if no executor implements it.

    TWO CALLERS, DELIBERATELY. The YAML validator rejects it at authoring time,
    which is cheap and early. This is also called at the EXECUTION boundary,
    because a template stored before this rule existed is rehydrated straight
    from its historical ``WorkflowTemplateCreated`` event and never sees the
    YAML validator - the same reason ``require_executable_provider`` guards
    execution rather than parsing alone. A loader-only check would sail every
    already-stored ``parallel`` phase straight through, which is precisely the
    population most likely to have one.
    """
    for known in IMPLEMENTED_EXECUTION_TYPES:
        if execution_type == known:
            return known
    raise UnsupportedExecutionTypeError(execution_type, phase_id=phase_id)


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


class FallbackAgent(BaseModel):
    """The agent a phase is re-run on, once, when its own provider cannot serve it (PC-83).

    Only for an upstream that refused the WHOLE attempt: capacity that outlived
    every retry, or a spent quota. Anything else the primary reported is the
    phase's answer and is not second-guessed by a different model. The phase's
    sandbox, tools, budget and prompt all apply unchanged.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    provider: str
    """'claude' or 'codex', from the workflow YAML ``fallback_agent.provider``."""

    model: str | None = None
    """Model for the fallback run; None resolves to the provider's default."""


def stored_fallback_agent(stored: object) -> FallbackAgent | None:
    """A phase's fallback agent as a projection stored it, or None when it declared none."""
    if stored is None:
        return None
    return FallbackAgent.model_validate(stored)


def stored_platform_access(stored: object) -> PlatformScope:
    """A phase's platform access as a projection stored it; READ when it predates #1744."""
    return PlatformScope.READ if stored is None else PlatformScope(str(stored))


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
    max_cost_usd: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    """The most this phase may spend, in USD, before it is stopped (#1376).

    The cost-axis twin of ``timeout_seconds``: None leaves the phase unbounded
    by cost. Positive and finite, here as well as in the YAML, because a
    template can be created without passing through the YAML."""
    allowed_tools: list[str] = Field(default_factory=list)
    """Tools allowed during this phase execution."""

    clone_repos: bool = True
    """Whether the workflow's repos are checked out for this phase (#1187).

    Sourced from the workflow YAML ``clone_repos`` field. False credentials
    the repos without checking them out, for a phase that talks to GitHub but
    needs no working tree. See ``PhaseYamlDefinition.clone_repos`` for why the
    repo list is deliberately still passed when this is False."""

    delivers_repo_changes: bool = True
    """Whether repository changes are part of this phase's deliverable (#1308).

    Sourced from the workflow YAML ``delivers_repo_changes`` field, and read by
    the unpushed-work gate to decide what an uncommitted change MEANS - a
    deliverable that was never saved, or a build tool's side effect. See
    ``PhaseYamlDefinition.delivers_repo_changes`` for why the gate cannot work
    this out for itself."""

    platform_access: PlatformScope = PlatformScope.READ
    """The scope of this phase's platform token (ADR-072, #1744).

    Sourced from the workflow YAML ``platform_access`` field; see
    ``PhaseYamlDefinition.platform_access``. READ unless the phase declared
    otherwise, which is also what every template stored before #1744 replays as."""
    requires_verdict: bool = False
    """Whether this phase must report a ``review_verdict`` (PC-116).

    Sourced from the workflow YAML ``requires_verdict`` field. When True, a
    run that reports none fails instead of advancing by order. See
    ``PhaseYamlDefinition.requires_verdict``."""

    # Claude Code command extensions (ISS-211)
    argument_hint: str | None = None
    """Describes what $ARGUMENTS expects for this phase (e.g., '[task-description]')."""

    model: str | None = None
    """Per-phase model override (e.g., 'sonnet', 'opus')."""

    model_defaulted: bool = False
    """Whether ``model`` was FILLED IN by the platform rather than declared.

    Set by the install and phase-edit handlers, never by a caller. True means
    the package declared no usable model and the operator's
    ``SYN_DEFAULT_*_MODEL`` was applied. A reinstall reads it to tell an
    unchanged undeclared model (a no-op) from a declared model the package has
    since removed (a change). Events written before this field existed replay
    as False, which is correct for them: their model was either declared or
    ``None``. No production event ever persisted a defaulted model without
    this flag - defaults were first persisted in the same change that added
    it - so the False default cannot mislabel a real default."""

    provider: str | None = None
    """Per-phase agent provider override ('claude' or 'codex').

    None means the execution default ('claude', the ``claude -p`` docker
    path). 'codex' routes the phase through the programmatic ``codex exec``
    harness on the same docker path. Sourced from the workflow YAML
    ``agent.provider`` field.
    """

    sandbox: str = DEFAULT_PHASE_SANDBOX
    """Authority level for this phase's agent process, from the workflow YAML
    ``agent.sandbox`` field.

    Defaults to ``DEFAULT_PHASE_SANDBOX``, which is currently the MOST
    permissive level, not the least - see there for why (#1157, #1161,
    #1167). A phase wanting less must declare it."""

    allow_delegation: bool = False
    """When true, both agent auths are staged so the phase's primary agent can
    delegate one-shot to the other CLI. Headless providers only. Sourced from
    the workflow YAML ``agent.allow_delegation`` field."""

    require_delegation: bool = False
    """When true, the phase completes only once a delegate to the other
    harness reported success (#894). Distinct from ``allow_delegation``, which
    is a permission and never gated. Sourced from the workflow YAML
    ``agent.require_delegation`` field."""

    fallback_agent: FallbackAgent | None = None
    """Re-run the phase once on this agent when the primary's upstream could
    not serve it (PC-83). Sourced from the workflow YAML ``fallback_agent``."""

    # Workflow-author-declared plugin refs at phase scope (issue #726). PR1 carries
    # them through the YAML to the domain; PR2's resolution service rewrites them
    # into ResolvedClaudePlugin entries on ExecutablePhase.
    claude_plugins: tuple[ClaudePluginRef, ...] = Field(default_factory=tuple)
    # Workflow-author-declared skill refs at phase scope (issue #772). Additive
    # alongside claude_plugins; carried through the YAML to the domain. A
    # follow-up resolution service rewrites them into ResolvedSkill entries
    # on ExecutablePhase.
    skills: tuple[SkillRef, ...] = Field(default_factory=tuple)
