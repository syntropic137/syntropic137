"""RecordOperation command - records an operation in a session."""

from __future__ import annotations

from typing import Any

from event_sourcing import command
from pydantic import BaseModel, ConfigDict, Field

from syn_domain.contexts.agent_sessions._shared.value_objects import OperationType  # noqa: TC001


@command("RecordOperation", "Records an operation in an agent session")
class RecordOperationCommand(BaseModel):
    """Command to record an operation (message, tool call, thinking, etc.).

    Operations track granular actions within a session for full observability.
    Use the appropriate operation_type and populate type-specific fields.
    """

    model_config = ConfigDict(frozen=True)

    # Target session
    aggregate_id: str = Field(..., description="Session ID to record operation in")

    # Operation details
    operation_type: OperationType
    duration_seconds: float | None = None
    success: bool = True

    # Token metrics (for MESSAGE_* types)
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None

    # Tool execution details (for TOOL_* types)
    tool_name: str | None = None
    tool_use_id: str | None = None  # Correlate TOOL_EXECUTION_STARTED/COMPLETED
    tool_input: dict[str, Any] | None = None  # Tool input parameters
    tool_output: str | None = None  # Tool output (truncated if large)

    # Message details (for MESSAGE_* types)
    message_role: str | None = None  # user, assistant, system
    message_content: str | None = None  # Message content (truncated)

    # Thinking details (for THINKING type)
    thinking_content: str | None = None  # Extended thinking (truncated)

    # Generic metadata
    metadata: dict[str, Any] | None = None
