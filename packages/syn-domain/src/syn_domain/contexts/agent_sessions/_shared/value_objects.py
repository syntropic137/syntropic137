"""Value objects for agent sessions bounded context.

Lane 1 domain truth — tokens only. Cost is Lane 2 telemetry (#695).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime  # noqa: TC003
from enum import StrEnum
from typing import Any


class SessionStatus(StrEnum):
    """Status of an agent session."""

    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class OperationType(StrEnum):
    """Type of operation recorded in a session.

    Operations track granular activities within an agent session.
    """

    # Messages (LLM API calls)
    MESSAGE_REQUEST = "message_request"  # User/system prompt sent to LLM
    MESSAGE_RESPONSE = "message_response"  # LLM response received

    # Tool lifecycle
    TOOL_EXECUTION_STARTED = "tool_started"  # Tool invocation began
    TOOL_EXECUTION_COMPLETED = "tool_completed"  # Tool finished (success/fail)
    TOOL_BLOCKED = "tool_blocked"  # Tool blocked by validator

    # Extended thinking
    THINKING = "thinking"  # Extended thinking content

    # Errors
    ERROR = "error"  # Error occurred

    # Legacy (deprecated, keep for backward compat)
    AGENT_REQUEST = "agent_request"  # Deprecated - use MESSAGE_*
    TOOL_EXECUTION = "tool_execution"  # Deprecated - use TOOL_*
    TOOL_USE = "tool_use"  # Deprecated - use TOOL_EXECUTION_COMPLETED
    VALIDATION = "validation"  # Keep for validation operations


@dataclass(frozen=True)
class TokenMetrics:
    """Token usage metrics.

    Immutable to ensure metrics are not accidentally modified.
    ``total_tokens`` is always computed from the four component fields.
    """

    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        """Total tokens (input + output + cache_creation + cache_read)."""
        return (
            self.input_tokens
            + self.output_tokens
            + self.cache_creation_tokens
            + self.cache_read_tokens
        )

    def __add__(self, other: TokenMetrics) -> TokenMetrics:
        """Add two TokenMetrics together."""
        return TokenMetrics(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            cache_creation_tokens=self.cache_creation_tokens + other.cache_creation_tokens,
            cache_read_tokens=self.cache_read_tokens + other.cache_read_tokens,
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
    tool_use_id: str | None = None  # Correlate TOOL_EXECUTION_STARTED/COMPLETED
    tool_input: dict[str, Any] | None = None  # Tool input parameters
    tool_output: str | None = None  # Tool output (truncated)

    # Message details (for MESSAGE_* types)
    message_role: str | None = None  # user, assistant, system
    message_content: str | None = None  # Message content (truncated)

    # Thinking details (for THINKING type)
    thinking_content: str | None = None  # Extended thinking (truncated)

    # Generic metadata
    metadata: dict[str, Any] = field(default_factory=dict)


# CostMetrics removed (#695): cost is Lane 2 telemetry.
# See session_cost projection for authoritative session cost.
