"""Value objects for workflow execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime  # noqa: TC003 - needed at runtime for dataclass
from enum import StrEnum
from typing import Any

from syn_shared.agents import AgentProvider


class ExecutionStatus(StrEnum):
    """Status of workflow execution."""

    NOT_STARTED = "not_started"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class PhaseStatus(StrEnum):
    """Status of a single phase execution."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass(frozen=True)
class AgentConfiguration:
    """Agent configuration for executing a phase.

    Immutable to ensure configuration integrity.

    NOTE: 'mock' provider is ONLY valid in test environments (APP_ENVIRONMENT=test).
    Production/development MUST use 'claude', 'claude-interactive', or 'codex'
    (or 'openai') with valid API keys/auth.

    Model Aliases (CLI-compatible, recommended):
        - "sonnet" -> latest Claude Sonnet
        - "opus" -> latest Claude Opus
        - "haiku" -> latest Claude Haiku

    'codex' selects the programmatic codex harness on the same docker path
    as 'claude' (not the interactive-tmux path). ``agent_id`` is meaningless
    on that path, so it MUST be ``None`` or ``"codex"`` when
    ``provider == "codex"`` - see ``__post_init__``.
    """

    provider: str = AgentProvider.CLAUDE  # + claude-interactive, codex, openai (mock in tests)
    # NOTE: Temporarily using Haiku to reduce costs during testing
    model: str = "haiku"  # CLI alias - auto-resolves to latest version
    max_tokens: int = 4096
    temperature: float = 0.7
    timeout_seconds: int = 300
    allowed_tools: tuple[str, ...] = ()  # Tools allowed during execution
    # Multi-agent interactive-tmux: which tmux pane the phase targets.
    # Valid values: "claude", "codex", "gemini". None means "not selected" -
    # distinguishable from an explicit "claude" pane choice. Ignored by the
    # default claude -p / codex docker path. See docs/plans/multi-agent-workspaces.md.
    agent_id: str | None = None
    # When true, both agent auths are staged so this phase's primary agent may
    # delegate one-shot to the other CLI. Default false = single-provider isolation.
    allow_delegation: bool = False

    def __post_init__(self) -> None:
        """Reject nonsensical provider/agent_id combinations.

        Mirrors ``aggregate_execution.value_objects.AgentConfiguration`` -
        keep both in sync.
        """
        if self.provider == AgentProvider.CODEX and self.agent_id not in (
            None,
            AgentProvider.CODEX,
        ):
            msg = (
                f"AgentConfiguration.provider='codex' selects the programmatic "
                f"codex harness; agent_id must be None or 'codex', got "
                f"{self.agent_id!r} (agent_id does not select a tmux pane on "
                "the docker path)."
            )
            raise ValueError(msg)


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
    """

    phase_id: str
    status: PhaseStatus
    started_at: datetime | None = None
    completed_at: datetime | None = None
    artifact_id: str | None = None
    session_id: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    error_message: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExecutionMetrics:
    """Aggregated metrics for workflow execution.

    Immutable summary of execution performance.
    """

    total_phases: int = 0
    completed_phases: int = 0
    failed_phases: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_tokens: int = 0
    total_duration_seconds: float = 0.0

    @classmethod
    def from_results(cls, results: list[PhaseResult]) -> ExecutionMetrics:
        """Create metrics from phase results."""
        completed = sum(1 for r in results if r.status == PhaseStatus.COMPLETED)
        failed = sum(1 for r in results if r.status == PhaseStatus.FAILED)

        total_input = sum(r.input_tokens for r in results)
        total_output = sum(r.output_tokens for r in results)
        total_tokens = sum(r.total_tokens for r in results)

        # Calculate total duration
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

    # Output artifact type
    output_artifact_type: str = "text"

    # Timeout for this phase (can override agent config)
    timeout_seconds: int | None = None
