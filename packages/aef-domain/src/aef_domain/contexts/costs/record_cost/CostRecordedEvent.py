"""CostRecorded event - emitted when a cost is incurred during a session."""

from __future__ import annotations

from dataclasses import field
from datetime import datetime  # noqa: TC003 - needed at runtime for DomainEvent
from decimal import Decimal  # noqa: TC003 - needed at runtime for DomainEvent
from typing import Any

from event_sourcing import DomainEvent, event


@event("CostRecorded", "v1")
class CostRecordedEvent(DomainEvent):
    """Event emitted when a cost is incurred during a session.

    This is the atomic cost event - each cost (token usage, tool execution)
    generates one of these events. The projection aggregates them into
    session-level and execution-level summaries.

    Attributes:
        session_id: The session where cost was incurred (primary key for atomic unit).
        execution_id: Optional execution this session belongs to.
        phase_id: Optional phase within the execution.
        workspace_id: Optional sandbox/workspace ID.
        cost_type: Type of cost ("llm_tokens" | "tool_execution" | "compute").
        amount_usd: Cost amount in USD.
        model: LLM model used (for token costs).
        input_tokens: Input tokens (for token costs).
        output_tokens: Output tokens (for token costs).
        cache_creation_tokens: Cache creation tokens (for token costs).
        cache_read_tokens: Cache read tokens (for token costs).
        tool_name: Tool name (for tool execution costs).
        tool_duration_ms: Tool execution duration in milliseconds.
        tool_token_breakdown: Per-tool token attribution (estimated).
        timestamp: When the cost was incurred.
        metadata: Additional metadata.
    """

    # Context - session is the atomic unit
    session_id: str

    # Linkage to execution hierarchy
    execution_id: str | None = None
    phase_id: str | None = None
    workspace_id: str | None = None

    # Cost details
    cost_type: str  # "llm_tokens" | "tool_execution" | "compute"
    amount_usd: Decimal

    # Token details (for llm_tokens type)
    model: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_creation_tokens: int | None = None
    cache_read_tokens: int | None = None

    # Tool details (for tool_execution type)
    tool_name: str | None = None
    tool_duration_ms: float | None = None

    # Tool token attribution (for llm_tokens type with tool calls)
    # Format: {"ToolName": {"tool_use": 100, "tool_result": 500}}
    tool_token_breakdown: dict[str, dict[str, int]] = field(default_factory=dict)

    # Timing
    timestamp: datetime | None = None

    # Generic metadata
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "event_type": "CostRecorded",
            "session_id": self.session_id,
            "execution_id": self.execution_id,
            "phase_id": self.phase_id,
            "workspace_id": self.workspace_id,
            "cost_type": self.cost_type,
            "amount_usd": str(self.amount_usd),
            "model": self.model,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_creation_tokens": self.cache_creation_tokens,
            "cache_read_tokens": self.cache_read_tokens,
            "tool_name": self.tool_name,
            "tool_duration_ms": self.tool_duration_ms,
            "tool_token_breakdown": self.tool_token_breakdown,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "metadata": self.metadata,
        }
