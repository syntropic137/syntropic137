"""SessionCostFinalized event - emitted when a session completes."""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 - needed at runtime for DomainEvent
from decimal import Decimal
from typing import Any

from event_sourcing import DomainEvent, event


@event("SessionCostFinalized", "v1")
class SessionCostFinalizedEvent(DomainEvent):
    """Event emitted when a session completes and its costs are finalized.

    This event contains the final aggregated costs for the session,
    enabling efficient queries without re-aggregating all CostRecordedEvents.

    Attributes:
        session_id: The session that completed.
        execution_id: Optional execution this session belongs to.
        phase_id: Optional phase within the execution.
        workspace_id: Optional sandbox/workspace ID.
        total_cost_usd: Total cost in USD.
        token_cost_usd: Cost from LLM tokens.
        compute_cost_usd: Cost from compute/tool execution.
        input_tokens: Total input tokens.
        output_tokens: Total output tokens.
        cache_creation_tokens: Total cache creation tokens.
        cache_read_tokens: Total cache read tokens.
        tool_calls: Total number of tool calls.
        turns: Total number of conversation turns.
        duration_ms: Total session duration in milliseconds.
        cost_by_model: Cost breakdown by model.
        cost_by_tool: Cost breakdown by tool.
        started_at: When the session started.
        completed_at: When the session completed.
    """

    # Context - session is the atomic unit
    session_id: str

    # Linkage to execution hierarchy
    execution_id: str | None = None
    phase_id: str | None = None
    workspace_id: str | None = None

    # Aggregated costs
    total_cost_usd: Decimal = Decimal("0")
    token_cost_usd: Decimal = Decimal("0")
    compute_cost_usd: Decimal = Decimal("0")

    # Aggregated token counts
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0

    # Aggregated metrics
    tool_calls: int = 0
    turns: int = 0
    duration_ms: float = 0

    # Breakdowns
    cost_by_model: dict[str, str] = {}  # noqa: RUF012  # Model -> USD as string
    cost_by_tool: dict[str, str] = {}  # noqa: RUF012  # Tool -> USD as string

    # Timing
    started_at: datetime | None = None
    completed_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "event_type": "SessionCostFinalized",
            "session_id": self.session_id,
            "execution_id": self.execution_id,
            "phase_id": self.phase_id,
            "workspace_id": self.workspace_id,
            "total_cost_usd": str(self.total_cost_usd),
            "token_cost_usd": str(self.token_cost_usd),
            "compute_cost_usd": str(self.compute_cost_usd),
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_creation_tokens": self.cache_creation_tokens,
            "cache_read_tokens": self.cache_read_tokens,
            "tool_calls": self.tool_calls,
            "turns": self.turns,
            "duration_ms": self.duration_ms,
            "cost_by_model": self.cost_by_model,
            "cost_by_tool": self.cost_by_tool,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }
