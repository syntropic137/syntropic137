"""Read model for session cost (atomic unit)."""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any


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

    # Status
    is_finalized: bool = False
    """Whether the session has completed."""

    started_at: datetime | None = None
    """When the session started."""

    completed_at: datetime | None = None
    """When the session completed."""

    @property
    def total_tokens(self) -> int:
        """Total tokens (input + output)."""
        return self.input_tokens + self.output_tokens

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SessionCost":
        """Create from dictionary."""
        # Convert string amounts back to Decimal
        cost_by_model = {
            k: Decimal(v) if isinstance(v, str) else v
            for k, v in data.get("cost_by_model", {}).items()
        }
        cost_by_tool = {
            k: Decimal(v) if isinstance(v, str) else v
            for k, v in data.get("cost_by_tool", {}).items()
        }
        tokens_by_tool = data.get("tokens_by_tool", {})
        cost_by_tool_tokens = {
            k: Decimal(v) if isinstance(v, str) else v
            for k, v in data.get("cost_by_tool_tokens", {}).items()
        }

        # Parse timestamps
        started_at = data.get("started_at")
        if isinstance(started_at, str):
            started_at = datetime.fromisoformat(started_at)

        completed_at = data.get("completed_at")
        if isinstance(completed_at, str):
            completed_at = datetime.fromisoformat(completed_at)

        # Parse Decimal fields
        total_cost = data.get("total_cost_usd", "0")
        if isinstance(total_cost, str):
            total_cost = Decimal(total_cost)

        token_cost = data.get("token_cost_usd", "0")
        if isinstance(token_cost, str):
            token_cost = Decimal(token_cost)

        compute_cost = data.get("compute_cost_usd", "0")
        if isinstance(compute_cost, str):
            compute_cost = Decimal(compute_cost)

        return cls(
            session_id=data.get("session_id", ""),
            execution_id=data.get("execution_id"),
            workflow_id=data.get("workflow_id"),
            phase_id=data.get("phase_id"),
            workspace_id=data.get("workspace_id"),
            total_cost_usd=total_cost,
            token_cost_usd=token_cost,
            compute_cost_usd=compute_cost,
            input_tokens=data.get("input_tokens", 0),
            output_tokens=data.get("output_tokens", 0),
            cache_creation_tokens=data.get("cache_creation_tokens", 0),
            cache_read_tokens=data.get("cache_read_tokens", 0),
            tool_calls=data.get("tool_calls", 0),
            turns=data.get("turns", 0),
            duration_ms=data.get("duration_ms", 0),
            cost_by_model=cost_by_model,
            cost_by_tool=cost_by_tool,
            tokens_by_tool=tokens_by_tool,
            cost_by_tool_tokens=cost_by_tool_tokens,
            is_finalized=data.get("is_finalized", False),
            agent_model=data.get("agent_model"),
            started_at=started_at,
            completed_at=completed_at,
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
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }
