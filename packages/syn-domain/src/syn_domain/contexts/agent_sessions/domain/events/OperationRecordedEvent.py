"""OperationRecorded event - represents the fact that an operation was recorded."""

from __future__ import annotations

from datetime import datetime  # noqa: TC003
from typing import Any

from event_sourcing import DomainEvent, event

from syn_domain.contexts.agent_sessions._shared.value_objects import OperationType  # noqa: TC001


@event("OperationRecorded", "v2")
class OperationRecordedEvent(DomainEvent):
    """Event emitted when an operation is recorded in a session.

    Supports multiple operation types for full observability:
    - MESSAGE_REQUEST/RESPONSE: LLM API calls
    - TOOL_EXECUTION_STARTED/COMPLETED/BLOCKED: Tool lifecycle
    - THINKING: Extended thinking content
    - ERROR: Error information

    Version History:
    - v1: Basic operation recording (tool_name, tokens, success)
    - v2: Full observability (tool I/O, messages, thinking content)
    """

    # Context
    session_id: str
    operation_id: str

    # The run this operation belongs to, and the key SSE routes on.
    #
    # Without it `RealTimeProjection._forward_event` has no channel to publish
    # to and drops the frame, so the event that fires on every tool call
    # reached no subscriber at all and the dashboard had to poll for the token
    # numbers it carries (#1095). Optional because a session can be started
    # outside a workflow execution, exactly as on SessionStarted; a missing
    # value means "no per-execution channel", not "unknown". Additive and
    # optional, so no upcaster and no version bump (ADR-007).
    execution_id: str | None = None

    # Operation details
    operation_type: OperationType
    timestamp: datetime
    duration_seconds: float | None = None
    success: bool = True

    # Token metrics (for MESSAGE_* types)
    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_creation_tokens: int | None = None
    cache_read_tokens: int | None = None
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
    metadata: dict[str, Any] = {}  # noqa: RUF012
