"""Read model for session cost (atomic unit)."""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any


class CostField(StrEnum):
    """A ``SessionCost`` field that a read path either measures or does not.

    Each member's VALUE is the field's own name, so a consumer holding one of
    these knows exactly which number not to trust without a lookup table.

    Exists because zero is not a truthful answer to "how much compute did this
    session cost" when nothing ever measured compute. ``PricingStatus`` draws
    that line for a single amount whose model has no rate (ADR-067 D3); this
    draws it for a whole field that no producer in the system fills. Issue
    #1041 stayed invisible for a month precisely because the dropped fields
    arrived as plausible zeroes.

    ``total_cost_usd`` is absent because every read path really does compute
    it. ``turns`` IS listed even though a read path can measure it, because
    only one can: ``num_turns`` exists on a ``session_summary`` event and
    nowhere else, so a session still running has no turn count rather than
    zero turns. That is the whole distinction - membership is per record, not
    per field.
    """

    COMPUTE_COST_USD = "compute_cost_usd"
    TOKENS_BY_TOOL = "tokens_by_tool"
    COST_BY_TOOL_TOKENS = "cost_by_tool_tokens"
    TURNS = "turns"


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


def _coerce_cost_fields(raw: object) -> frozenset[CostField]:
    """Coerce stored field names back to ``CostField``.

    A key absent from an older stored record means it predates the
    distinction, and every one of these fields was unmeasured then too - so
    absent coerces to the full set, not to the empty one. Empty would claim
    the old record had measured them all, which is the silent zero this type
    exists to prevent, restored via the persistence hop.
    """
    if raw is None:
        return frozenset(CostField)
    if not isinstance(raw, (list, tuple, set, frozenset)):
        return frozenset(CostField)
    return frozenset(CostField(name) for name in raw if name in set(CostField))


@dataclass
class SessionCost:
    """Cost for a single session (atomic unit).

    A session = single agent + single phase + single sandbox.
    This is the atomic unit for cost tracking.
    """

    session_id: str
    """The session identifier."""

    # Linkage to execution hierarchy
    execution_id: str | None = None
    """Optional execution this session belongs to."""

    workflow_id: str | None = None
    """Optional workflow this session belongs to."""

    phase_id: str | None = None
    """Optional phase within the execution."""

    workspace_id: str | None = None
    """Optional sandbox/workspace ID."""

    # Cost totals
    total_cost_usd: Decimal = Decimal("0")
    """Total cost in USD."""

    token_cost_usd: Decimal = Decimal("0")
    """Cost from LLM tokens."""

    compute_cost_usd: Decimal = Decimal("0")
    """Cost from compute/tool execution."""

    # Token counts
    input_tokens: int = 0
    """Total input tokens."""

    output_tokens: int = 0
    """Total output tokens."""

    cache_creation_tokens: int = 0
    """Total cache creation tokens."""

    cache_read_tokens: int = 0
    """Total cache read tokens."""

    # Metrics
    tool_calls: int = 0
    """Total number of tool calls."""

    turns: int = 0
    """Total number of conversation turns."""

    duration_ms: float = 0
    """Total session duration in milliseconds."""

    # Breakdowns
    cost_by_model: dict[str, Decimal] = field(default_factory=dict)
    """Cost breakdown by model."""

    cost_by_tool: dict[str, Decimal] = field(default_factory=dict)
    """Cost breakdown by tool (execution costs)."""

    tokens_by_tool: dict[str, int] = field(default_factory=dict)
    """Token breakdown by tool (estimated)."""

    cost_by_tool_tokens: dict[str, Decimal] = field(default_factory=dict)
    """Token cost breakdown by tool (derived from tokens_by_tool)."""

    # Model
    agent_model: str | None = None
    """Primary model used for this session (from CLI result event)."""

    unpriced_observation_count: int = 0
    """Count of TOKEN_USAGE observations whose model was unknown/missing.

    These contribute zero cost to ``total_cost_usd`` (never priced as a
    default/guessed model - see issue #788). A non-zero count means the
    total is incomplete, not confidently wrong.
    """

    unmeasured_fields: frozenset[CostField] = field(default_factory=lambda: frozenset(CostField))
    """Fields whose value on this record was never measured, only defaulted.

    Defaults to EVERY member of ``CostField``, so a record is presumed not to
    have measured them until a producer says otherwise via ``record_measured``.
    That direction is the point: the failure mode of forgetting is then a field
    that honestly reports itself unmeasured, rather than one that reports a
    confident zero. #1041 was the second kind, and it survived a month of use.

    Today no producer measures any of them - ``agent_events`` records no
    per-tool token counts and there is no compute rate table - so this is the
    full set on every read path. Emptying it is what a future producer of one
    of these fields has to do, and until it does, a zero here means "nobody
    counted", not "it was free".
    """

    # Status
    is_finalized: bool = False
    """Whether the session has completed."""

    started_at: datetime | None = None
    """When the session started."""

    completed_at: datetime | None = None
    """When the session completed."""

    def record_measured(self, cost_field: CostField) -> None:
        """Declare that this record's value for *cost_field* was really computed.

        Call it beside the assignment it vouches for; the two together are what
        makes the number readable as a measurement rather than a default.
        """
        self.unmeasured_fields -= {cost_field}

    @property
    def total_tokens(self) -> int:
        """Total tokens (input + output + cache creation + cache read).

        All four components are summed so this agrees with the executions
        read model, which reports the same figure under the same name
        (issue #873). Cache reads dominate agent sessions, so omitting them
        undercounted this by up to ~68x while cost stayed correct, because
        pricing reads the cache fields directly.
        """
        return (
            self.input_tokens
            + self.output_tokens
            + self.cache_creation_tokens
            + self.cache_read_tokens
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SessionCost":
        """Create from dictionary."""
        return cls(
            session_id=data.get("session_id", ""),
            execution_id=data.get("execution_id"),
            workflow_id=data.get("workflow_id"),
            phase_id=data.get("phase_id"),
            workspace_id=data.get("workspace_id"),
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
            cost_by_model=_coerce_decimal_dict(data.get("cost_by_model")),
            cost_by_tool=_coerce_decimal_dict(data.get("cost_by_tool")),
            tokens_by_tool=data.get("tokens_by_tool", {}),
            cost_by_tool_tokens=_coerce_decimal_dict(data.get("cost_by_tool_tokens")),
            is_finalized=data.get("is_finalized", False),
            agent_model=data.get("agent_model"),
            unpriced_observation_count=data.get("unpriced_observation_count", 0),
            unmeasured_fields=_coerce_cost_fields(data.get("unmeasured_fields")),
            started_at=_coerce_datetime(data.get("started_at")),
            completed_at=_coerce_datetime(data.get("completed_at")),
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "session_id": self.session_id,
            "execution_id": self.execution_id,
            "workflow_id": self.workflow_id,
            "phase_id": self.phase_id,
            "workspace_id": self.workspace_id,
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
            "cost_by_model": {k: str(v) for k, v in self.cost_by_model.items()},
            "cost_by_tool": {k: str(v) for k, v in self.cost_by_tool.items()},
            "tokens_by_tool": self.tokens_by_tool,
            "cost_by_tool_tokens": {k: str(v) for k, v in self.cost_by_tool_tokens.items()},
            "is_finalized": self.is_finalized,
            "agent_model": self.agent_model,
            "unpriced_observation_count": self.unpriced_observation_count,
            "unmeasured_fields": sorted(self.unmeasured_fields),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }
