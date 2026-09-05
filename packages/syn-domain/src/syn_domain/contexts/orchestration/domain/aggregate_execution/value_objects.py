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


class BranchObservation(BaseModel):
    """One remote branch of a failing phase's workspace, as git had it (#1200).

    WHERE TO LOOK, WITHOUT SAYING WHO PUT IT THERE. A phase can commit, push,
    and still fail - most often on the #1167 output-artifact contract - and
    when it does no PR is opened and no surface names the branch. The work is
    complete, reviewed by nobody, and findable only by someone who thinks to
    go through the remote's refs. Twice in one day that someone was a human
    doing it by hand; both rescues merged.

    EVERY FIELD IS SOMETHING GIT WAS ASKED AND ANSWERED, and nothing here is
    an attribution. An earlier version of this recorded "work THIS PHASE
    pushed", derived by snapshotting the refs at phase start and treating
    whatever was new as the phase's own. That signature is produced just as
    well by a concurrent push or a human's, because a ref that moved between
    two readings does not record who moved it: git carries no author of a
    push. So the comparison is still taken and still reported - as the
    comparison it is, two SHAs and the reader's own eyes - and no field claims
    the phase caused it.

    That is enough for the operator the record exists for. "Where do I look"
    is answered by a branch name and a commit; it never required knowing who
    pushed.

    A Pydantic model rather than a dataclass because it travels on
    ``WorkflowFailedEvent`` and must serialise as event data.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    repo: str
    """The repository directory's name, as the workspace had it cloned."""

    branch: str
    """The branch the workspace was on, without any remote prefix - the name
    to fetch, and the name a PR would be opened from. ``(detached HEAD)`` when
    it was not on one."""

    remote: str | None
    """The remote this observation is about, e.g. ``origin``. ``None`` when
    the branch has no remote-tracking ref and had none at phase start, so
    there is no remote branch to describe. One observation per remote that
    carries the branch, rather than one per repository picking a remote by
    some rule nobody can see."""

    remote_commit: str | None
    """What ``<remote>/<branch>`` points at NOW, asked of the remote itself
    while the workspace was still alive. ``None`` means the remote does not
    have that branch - never pushed, or deleted while the phase ran.

    Read from the remote and not from `refs/remotes`, which is only what this
    clone was last told: a phase that never fetched would report a commit that
    predates whatever it is being compared against. A remote that could not be
    reached produces no record at all rather than a stale one; see
    `ObservedBranches.unreadable`."""

    remote_commit_at_phase_start: str | None
    """What that same ref pointed at when the phase was handed the workspace,
    from `PhaseStartingPoint`. ``None`` means the ref did not exist then.

    Reported beside `remote_commit` rather than reduced to a verdict: the two
    together say "it moved" without anyone having to claim who moved it, and
    an operator diffing them gets more than a boolean would give."""

    unpushed_commits: int
    """How many commits are reachable from the workspace's HEAD that no remote
    ref holds. ``0`` is a fact about the repository and not about the phase.

    Non-zero is a DIFFERENT INCIDENT from a remote that moved: those commits
    are about to die with the container, which is #1184's quarantine to save
    and not something to fetch. Keeping the count here is what lets a client
    tell "this phase left nothing anywhere" from "this phase is holding work
    that is not on any remote" without reading prose."""

    @property
    def remote_moved(self) -> bool:
        """Whether ``<remote>/<branch>`` is at a different commit than at start.

        A comparison of two readings, and deliberately not called anything
        like "pushed": it is true of a push from this workspace, a push from
        anywhere else, and a ref someone deleted or recreated in between.
        """
        return self.remote_commit != self.remote_commit_at_phase_start

    @property
    def is_worth_recording(self) -> bool:
        """Whether anything here differs from a workspace nobody touched.

        The one place that decides what a record MEANS by deciding when one
        exists. A repository whose remote branch is where it was and whose
        HEAD is fully pushed has nothing an operator would act on, and
        recording it anyway is how a phase that did nothing came to report the
        commit it inherited as somewhere to go and look.
        """
        return self.remote_moved or self.unpushed_commits > 0


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
