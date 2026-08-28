"""Read model for execution cost (aggregated from sessions)."""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Final

UNATTRIBUTED_PHASE_ID: Final[str] = "unattributed"
"""Bucket for cost that belongs to an execution but to no particular phase.

``agent_events.phase_id`` is nullable, so a session_summary can be recorded
against an execution without a phase. The execution total counts that spend;
if the per-phase breakdown silently skipped it, the parts would not add up
to the whole (issue #812). Naming the bucket keeps the breakdown honest and
the gap visible instead of invisible.
"""


def _coerce_decimal(value: str | Decimal | int | float | None, default: str = "0") -> Decimal:
    """Coerce a value to Decimal, returning *default* when None."""
    if value is None:
        return Decimal(default)
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _coerce_datetime(value: str | datetime | None) -> datetime | None:
    """Coerce a value to datetime, returning None when not parseable."""
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return value


def _coerce_decimal_dict(raw: dict[str, str | Decimal] | None) -> dict[str, Decimal]:
    """Coerce a dict of string/Decimal values to Decimal values."""
    if not raw:
        return {}
    return {k: _coerce_decimal(v) for k, v in raw.items()}


@dataclass
class ExecutionCost:
    """Aggregated cost for a workflow execution.

    Rolls up costs from all sessions (phases) in the execution.
    """

    execution_id: str
    """The execution identifier."""

    workflow_id: str | None = None
    """Optional workflow identifier."""

    # Session tracking
    session_count: int = 0
    """Number of sessions in this execution."""

    session_ids: list[str] = field(default_factory=list)
    """List of session IDs that contributed to this cost."""

    # Cost totals (sum of session costs)
    total_cost_usd: Decimal = Decimal("0")
    """Total cost in USD."""

    token_cost_usd: Decimal = Decimal("0")
    """Cost from LLM tokens."""

    compute_cost_usd: Decimal = Decimal("0")
    """Cost from compute/tool execution."""

    # Aggregated token counts
    input_tokens: int = 0
    """Total input tokens across all sessions."""

    output_tokens: int = 0
    """Total output tokens across all sessions."""

    cache_creation_tokens: int = 0
    """Total cache creation tokens across all sessions."""

    cache_read_tokens: int = 0
    """Total cache read tokens across all sessions."""

    # Aggregated metrics
    tool_calls: int = 0
    """Total number of tool calls across all sessions."""

    turns: int = 0
    """Total number of conversation turns across all sessions."""

    duration_ms: float = 0
    """Total duration in milliseconds across all sessions."""

    # Breakdowns
    cost_by_phase: dict[str, Decimal] = field(default_factory=dict)
    """Cost breakdown by phase.

    Spend that cannot be attributed to a phase is bucketed under
    ``UNATTRIBUTED_PHASE_ID`` rather than dropped, so this breakdown always
    reconciles with ``total_cost_usd`` (issue #812). ``phase_id`` is
    nullable on ``agent_events``, so phase-less summaries are a real state,
    not a corruption.
    """

    models_by_phase: dict[str, dict[str, Decimal]] = field(default_factory=dict)
    """What each MODEL cost within a phase.

    Since #895 a phase can contain more than one session: a delegated run is
    priced under its own session id but the same phase_id. ``cost_by_phase``
    can only say what the phase cost in total; this says which model spent it,
    which is the number that decides whether more fan-out is affordable.
    """

    unpriced_by_phase: dict[str, int] = field(default_factory=dict)
    """Per-phase count of observations that could not be priced.

    ``cost_by_phase`` can only say "this phase cost $X". It has no way to say
    "we do not know what this phase cost", so an unpriced phase either vanished
    from the breakdown or showed up as ``$0.00`` - the same ambiguity #890 fixes
    at the execution level, one level down. A phase listed here contributed real
    work that carries no rate.
    """

    cost_by_model: dict[str, Decimal] = field(default_factory=dict)
    """Cost breakdown by model."""

    cost_by_tool: dict[str, Decimal] = field(default_factory=dict)
    """Cost breakdown by tool."""

    unpriced_observation_count: int = 0
    """Count of TOKEN_USAGE observations whose model was unknown/missing.

    These contribute zero cost to ``total_cost_usd`` (never priced as a
    default/guessed model - see issue #788). A non-zero count means the
    total is incomplete, not confidently wrong.
    """

    # Status
    is_complete: bool = False
    """Whether all sessions have completed."""

    started_at: datetime | None = None
    """When the first session started."""

    completed_at: datetime | None = None
    """When the last session completed."""

    @property
    def total_tokens(self) -> int:
        """Total tokens (input + output + cache creation + cache read).

        All four components are summed so this agrees with the executions
        read model, which reports the same figure under the same name
        (issue #873). Cost is unaffected: pricing reads the four component
        fields directly and never goes through this property.
        """
        return (
            self.input_tokens
            + self.output_tokens
            + self.cache_creation_tokens
            + self.cache_read_tokens
        )

    @property
    def has_cost_data(self) -> bool:
        """Whether this record carries cost data worth preferring over a fallback.

        Deliberately NOT ``total_tokens > 0``. ``total_tokens`` is a DISPLAY
        figure that grew to include cache tokens in issue #873; wiring dollar
        selection to it would let a cache-only record (input == output == 0)
        newly satisfy the gate and flip the reported dollar figure from the
        caller's fallback to ``total_cost_usd``. #873 was a display fix that
        was required to move no dollars, so the availability predicate keeps
        the input + output shape it had before that change.

        ``is_complete`` would be the better long-term predicate but is not a
        drop-in: it is False for an execution still running, and the API
        enriches in-progress executions today. Swapping to it would change
        behaviour for live executions, which is a separate decision from this
        one. ``unpriced_observation_count`` measures confidence in the total,
        not whether a total exists, so it does not answer this question either.
        """
        return self.input_tokens + self.output_tokens > 0

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ExecutionCost":
        """Create from dictionary."""
        return cls(
            execution_id=data.get("execution_id", ""),
            workflow_id=data.get("workflow_id"),
            session_count=data.get("session_count", 0),
            session_ids=data.get("session_ids", []),
            total_cost_usd=_coerce_decimal(data.get("total_cost_usd", "0")),
            token_cost_usd=_coerce_decimal(data.get("token_cost_usd", "0")),
            compute_cost_usd=_coerce_decimal(data.get("compute_cost_usd", "0")),
            input_tokens=data.get("input_tokens", 0),
            output_tokens=data.get("output_tokens", 0),
            cache_creation_tokens=data.get("cache_creation_tokens", 0),
            cache_read_tokens=data.get("cache_read_tokens", 0),
            tool_calls=data.get("tool_calls", 0),
            turns=data.get("turns", 0),
            duration_ms=data.get("duration_ms", 0),
            cost_by_phase=_coerce_decimal_dict(data.get("cost_by_phase")),
            models_by_phase={
                phase: _coerce_decimal_dict(models)
                for phase, models in (data.get("models_by_phase") or {}).items()
            },
            unpriced_by_phase=dict(data.get("unpriced_by_phase") or {}),
            cost_by_model=_coerce_decimal_dict(data.get("cost_by_model")),
            cost_by_tool=_coerce_decimal_dict(data.get("cost_by_tool")),
            unpriced_observation_count=data.get("unpriced_observation_count", 0),
            is_complete=data.get("is_complete", False),
            started_at=_coerce_datetime(data.get("started_at")),
            completed_at=_coerce_datetime(data.get("completed_at")),
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "execution_id": self.execution_id,
            "workflow_id": self.workflow_id,
            "session_count": self.session_count,
            "session_ids": self.session_ids,
            "total_cost_usd": str(self.total_cost_usd),
            "token_cost_usd": str(self.token_cost_usd),
            "compute_cost_usd": str(self.compute_cost_usd),
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_creation_tokens": self.cache_creation_tokens,
            "cache_read_tokens": self.cache_read_tokens,
            "total_tokens": self.total_tokens,
            "tool_calls": self.tool_calls,
            "turns": self.turns,
            "duration_ms": self.duration_ms,
            "cost_by_phase": {k: str(v) for k, v in self.cost_by_phase.items()},
            "models_by_phase": {
                phase: {m: str(c) for m, c in models.items()}
                for phase, models in self.models_by_phase.items()
            },
            "unpriced_by_phase": dict(self.unpriced_by_phase),
            "cost_by_model": {k: str(v) for k, v in self.cost_by_model.items()},
            "cost_by_tool": {k: str(v) for k, v in self.cost_by_tool.items()},
            "unpriced_observation_count": self.unpriced_observation_count,
            "is_complete": self.is_complete,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }
