"""Value objects for workflow execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime  # noqa: TC003 - needed at runtime for dataclass
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict

from syn_domain.contexts.orchestration._shared.resolved_claude_plugin import (
    ResolvedClaudePlugin,  # noqa: TC001 - needed at runtime for dataclass field default
)
from syn_domain.contexts.orchestration._shared.resolved_skill import (
    ResolvedSkill,  # noqa: TC001 - needed at runtime for dataclass field default
)
from syn_shared.agents import (
    DEFAULT_PHASE_SANDBOX,
    AgentProvider,
    resolve_phase_model,
)


class ExecutionStatus(StrEnum):
    """Status of workflow execution."""

    NOT_STARTED = "not_started"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"


class PhaseStatus(StrEnum):
    """Status of a single phase execution."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass(frozen=True)
class PhaseDefinition:
    """Immutable definition of a phase for aggregate-level sequencing.

    Used by the aggregate to know phase ordering and decide "what's next"
    after artifacts are collected. The aggregate owns sequencing decisions.
    """

    phase_id: str
    name: str
    order: int
    timeout_seconds: int = 300


@dataclass(frozen=True)
class AgentConfiguration:
    """Agent configuration for executing a phase.

    Immutable to ensure configuration integrity.

    NOTE: 'mock' provider is ONLY valid in test environments (APP_ENVIRONMENT=test).
    Production/development MUST use 'claude' or 'codex'
    (or 'openai') with valid API keys/auth.

    Model Aliases (CLI-compatible, recommended):
        - "sonnet" -> latest Claude Sonnet
        - "opus" -> latest Claude Opus
        - "haiku" -> latest Claude Haiku

    'codex' selects the programmatic codex harness on the same docker path
    as 'claude'.
    """

    provider: str = AgentProvider.CLAUDE  # + codex, openai (mock in tests)
    # Declared default is None = "caller named no model". __post_init__ then
    # resolves it PER PROVIDER: Claude gets DEFAULT_CLAUDE_MODEL, codex stays
    # None because codex does not report its own model on the wire and a
    # synthesized value would price every codex run as Haiku (issue #788).
    # Resolution lives here, not in a caller, so EVERY construction path gets
    # it - a caller-side default only covered phases built from YAML.
    model: str | None = None  # CLI alias - auto-resolves to latest version
    max_tokens: int = 4096
    temperature: float = 0.7
    timeout_seconds: int = 300
    allowed_tools: tuple[str, ...] = ()  # Tools allowed during execution
    # How much authority this phase's agent process gets. Steers codex only;
    # claude scopes through allowed_tools. The command builder maps it to the
    # harness flag. Defaults to DEFAULT_PHASE_SANDBOX, currently the MOST
    # permissive level as a stopgap - see PhaseSandbox (#1157, #1161, #1167).
    sandbox: str = DEFAULT_PHASE_SANDBOX
    # When true, both agent auths are staged so this phase's primary agent may
    # delegate one-shot to the other CLI. Default false = single-provider isolation.
    allow_delegation: bool = False

    def __post_init__(self) -> None:
        """Resolve the per-provider model default.

        Mirrors ``_shared.ExecutionValueObjects.AgentConfiguration`` - keep
        both in sync.
        """
        resolved_model = resolve_phase_model(self.provider, self.model)
        if resolved_model != self.model:
            object.__setattr__(self, "model", resolved_model)


@dataclass(frozen=True)
class PhaseInput:
    """Input specification for a phase.

    Can be from initial workflow inputs or from a previous phase's artifact.
    """

    name: str
    value: str | None = None  # Direct value
    from_phase: str | None = None  # Reference to previous phase output


@dataclass(frozen=True)
class PhaseResult:
    """Result of a single phase execution.

    Immutable record of what happened during phase execution.
    Tokens are domain truth (Lane 1); cost is Lane 2 telemetry and does not
    live on this value object.
    """

    phase_id: str
    status: PhaseStatus
    started_at: datetime | None = None
    completed_at: datetime | None = None
    artifact_id: str | None = None
    session_id: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0
    total_tokens: int = 0
    error_message: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class PushedWork(BaseModel):
    """One repository's work that a failing phase had already put on a remote (#1200).

    THE FACT AN OPERATOR NEEDS AT 2AM, and the one a failed execution used to
    throw away. A phase can commit, push, and still fail - most often on the
    #1167 output-artifact contract - and when it does, no PR is opened and no
    surface names the branch. The work is complete, reviewed by nobody, and
    findable only by someone who thinks to go looking through the remote's
    refs. Twice in one day that someone was a human doing it by hand; both
    rescues merged.

    EVERY INSTANCE IS A TRUE CLAIM ABOUT THE REMOTE, AND ABOUT THIS PHASE.
    One is only ever built after a remote-tracking ref was found to contain
    ``commit`` - never from "the phase had a branch name", which is the mistake
    #1184 took four review passes to get out of its own recoverability
    reporting - and only for a commit that was NOT in the workspace when the
    phase began. Without that second half a phase that did nothing reported the
    branch it was handed as its own output, which is a true sentence about git
    and a false answer to "where did this phase's work go". A phase that pushed
    nothing therefore produces NO instances rather than an instance saying so:
    absence is the honest shape for "there is nothing to fetch", because a
    record shaped like a location invites being read as one.

    A Pydantic model rather than a dataclass because it travels on
    ``WorkflowFailedEvent`` and must serialise as event data.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    repo: str
    """The repository directory's name, as the workspace had it cloned."""

    branch: str
    """The branch the phase was on, without its remote prefix - i.e. the name
    to fetch, and the name a PR would be opened from. Its remote-tracking ref
    is what was found to contain ``commit``."""

    commit: str
    """The commit an operator should look at: the newest one this phase
    produced that its branch's remote is confirmed to hold. Usually HEAD, and
    not HEAD when the phase pushed and then committed again - the later commits
    are not on the remote, so they are not offered here."""


@dataclass(frozen=True)
class ExecutionMetrics:
    """Aggregated metrics for workflow execution.

    Immutable summary of execution performance. Cost is Lane 2 telemetry —
    see execution_cost projection.
    """

    total_phases: int = 0
    completed_phases: int = 0
    failed_phases: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cache_creation_tokens: int = 0
    total_cache_read_tokens: int = 0
    total_tokens: int = 0
    total_duration_seconds: float = 0.0

    @classmethod
    def from_results(cls, results: list[PhaseResult]) -> ExecutionMetrics:
        """Create metrics from phase results."""
        completed = sum(1 for r in results if r.status == PhaseStatus.COMPLETED)
        failed = sum(1 for r in results if r.status == PhaseStatus.FAILED)

        total_input = sum(r.input_tokens for r in results)
        total_output = sum(r.output_tokens for r in results)
        total_cache_creation = sum(r.cache_creation_tokens for r in results)
        total_cache_read = sum(r.cache_read_tokens for r in results)
        total_tokens = sum(r.total_tokens for r in results)

        duration = 0.0
        for result in results:
            if result.started_at and result.completed_at:
                delta = result.completed_at - result.started_at
                duration += delta.total_seconds()

        return cls(
            total_phases=len(results),
            completed_phases=completed,
            failed_phases=failed,
            total_input_tokens=total_input,
            total_output_tokens=total_output,
            total_cache_creation_tokens=total_cache_creation,
            total_cache_read_tokens=total_cache_read,
            total_tokens=total_tokens,
            total_duration_seconds=duration,
        )


@dataclass(frozen=True)
class ExecutablePhase:
    """Phase with full execution configuration.

    Combines phase definition with runtime execution config.

    NOTE: All phases MUST have a prompt_template and valid agent_config.
    Empty prompts will cause agent calls to fail.
    """

    phase_id: str
    name: str
    order: int
    description: str | None = None

    # Agent configuration - defaults to Claude (real agent)
    agent_config: AgentConfiguration = field(default_factory=AgentConfiguration)

    # Prompt template (REQUIRED - actual template, not ID)
    prompt_template: str = ""  # Must be set by workflow definition

    # Input configuration
    inputs: list[PhaseInput] = field(default_factory=list)

    # What this phase's definition declares it produces. Plural and possibly
    # EMPTY, which is the whole point: empty means "declared nothing" and is a
    # phase legitimately allowed to produce nothing, while a non-empty
    # declaration is a contract the collector enforces (#1167). The previous
    # singular `output_artifact_type: str = "text"` could not express the
    # difference - an undeclared phase and one declaring "text" both arrived
    # here as "text", so no enforcement was possible downstream.
    output_artifact_types: tuple[str, ...] = ()

    # Timeout for this phase (can override agent config)
    timeout_seconds: int | None = None

    # Whether this phase's workspace gets the repos checked out (#1187).
    # Provisioning was phase-blind: the only opt-out was workflow-level
    # `requires_repos: false`, which applies to every phase at once. Carried
    # here rather than on `agent_config` because it decides what the WORKSPACE
    # contains, not how the agent is invoked.
    clone_repos: bool = True

    # Resolved plugins for the workspace materializer (issue #726). PR1 leaves
    # this empty; PR2's resolution service populates it from the workflow- and
    # phase-scope ClaudePluginRefs.
    claude_plugins: tuple[ResolvedClaudePlugin, ...] = ()

    # Resolved skills for the workspace materializer (issue #772). Additive
    # alongside claude_plugins. ExecuteWorkflowHandler._resolve_phase_skills
    # populates it from the workflow- and phase-scope SkillRefs, with phase
    # scope winning on identity collision.
    skills: tuple[ResolvedSkill, ...] = ()
