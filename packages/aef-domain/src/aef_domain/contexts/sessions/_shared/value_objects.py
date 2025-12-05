"""Value objects for agent sessions bounded context."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime  # noqa: TC003
from decimal import Decimal
from enum import Enum
from typing import Any


class SessionStatus(str, Enum):
    """Status of an agent session."""

    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class OperationType(str, Enum):
    """Type of operation recorded in a session.

    Operations track granular activities within an agent session.
    """

    # Messages (LLM API calls)
    MESSAGE_REQUEST = "message_request"  # User/system prompt sent to LLM
    MESSAGE_RESPONSE = "message_response"  # LLM response received

    # Tool lifecycle
    TOOL_STARTED = "tool_started"  # Tool invocation began
    TOOL_COMPLETED = "tool_completed"  # Tool finished (success/fail)
    TOOL_BLOCKED = "tool_blocked"  # Tool blocked by validator

    # Extended thinking
    THINKING = "thinking"  # Extended thinking content

    # Errors
    ERROR = "error"  # Error occurred

    # Legacy (deprecated, keep for backward compat)
    AGENT_REQUEST = "agent_request"  # Deprecated - use MESSAGE_*
    TOOL_EXECUTION = "tool_execution"  # Deprecated - use TOOL_*
    TOOL_USE = "tool_use"  # Deprecated - use TOOL_COMPLETED
    VALIDATION = "validation"  # Keep for validation operations


@dataclass(frozen=True)
class TokenMetrics:
    """Token usage metrics.

    Immutable to ensure metrics are not accidentally modified.
    """

    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0

    def __add__(self, other: TokenMetrics) -> TokenMetrics:
        """Add two TokenMetrics together."""
        return TokenMetrics(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            total_tokens=self.total_tokens + other.total_tokens,
        )


@dataclass(frozen=True)
class OperationRecord:
    """Record of a single operation in a session.

    Immutable to ensure operation history is not modified.
    Supports different operation types with type-specific fields.
    """

    operation_id: str
    operation_type: OperationType
    timestamp: datetime
    duration_seconds: float | None = None
    tokens: TokenMetrics | None = None
    success: bool = True

    # Tool execution details (for TOOL_* types)
    tool_name: str | None = None
    tool_use_id: str | None = None  # Correlate TOOL_STARTED/COMPLETED
    tool_input: dict[str, Any] | None = None  # Tool input parameters
    tool_output: str | None = None  # Tool output (truncated)

    # Message details (for MESSAGE_* types)
    message_role: str | None = None  # user, assistant, system
    message_content: str | None = None  # Message content (truncated)

    # Thinking details (for THINKING type)
    thinking_content: str | None = None  # Extended thinking (truncated)

    # Generic metadata
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CostMetrics:
    """Cost metrics for a session.

    All costs in USD.
    """

    input_cost_usd: Decimal = Decimal("0")
    output_cost_usd: Decimal = Decimal("0")
    total_cost_usd: Decimal = Decimal("0")

    def __add__(self, other: CostMetrics) -> CostMetrics:
        """Add two CostMetrics together."""
        return CostMetrics(
            input_cost_usd=self.input_cost_usd + other.input_cost_usd,
            output_cost_usd=self.output_cost_usd + other.output_cost_usd,
            total_cost_usd=self.total_cost_usd + other.total_cost_usd,
        )

    @classmethod
    def from_tokens(
        cls,
        input_tokens: int,
        output_tokens: int,
        input_price_per_1k: Decimal = Decimal("0.01"),
        output_price_per_1k: Decimal = Decimal("0.03"),
    ) -> CostMetrics:
        """Calculate cost from token counts.

        Default prices are conservative estimates for premium models.

        Args:
            input_tokens: Number of input tokens.
            output_tokens: Number of output tokens.
            input_price_per_1k: Price per 1000 input tokens.
            output_price_per_1k: Price per 1000 output tokens.

        Returns:
            CostMetrics with calculated costs.
        """
        input_cost = (Decimal(input_tokens) / 1000) * input_price_per_1k
        output_cost = (Decimal(output_tokens) / 1000) * output_price_per_1k
        return cls(
            input_cost_usd=input_cost,
            output_cost_usd=output_cost,
            total_cost_usd=input_cost + output_cost,
        )
