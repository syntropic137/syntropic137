"""Read model for execution cost (aggregated from sessions)."""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

from syn_domain.contexts.agent_sessions.domain.read_models.session_cost import (
    _coerce_datetime,
    _coerce_decimal,
    _coerce_decimal_dict,
)


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
    """Cost breakdown by phase."""

    cost_by_model: dict[str, Decimal] = field(default_factory=dict)
    """Cost breakdown by model."""

    cost_by_tool: dict[str, Decimal] = field(default_factory=dict)
    """Cost breakdown by tool."""

    # Status
    is_complete: bool = False
    """Whether all sessions have completed."""

    started_at: datetime | None = None
    """When the first session started."""

    completed_at: datetime | None = None
    """When the last session completed."""

    @property
    def total_tokens(self) -> int:
        """Total tokens (input + output)."""
        return self.input_tokens + self.output_tokens

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
            cost_by_model=_coerce_decimal_dict(data.get("cost_by_model")),
            cost_by_tool=_coerce_decimal_dict(data.get("cost_by_tool")),
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
            "cost_by_model": {k: str(v) for k, v in self.cost_by_model.items()},
            "cost_by_tool": {k: str(v) for k, v in self.cost_by_tool.items()},
            "is_complete": self.is_complete,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }
