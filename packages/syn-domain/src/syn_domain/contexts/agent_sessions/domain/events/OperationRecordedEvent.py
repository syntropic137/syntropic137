"""OperationRecorded event - represents the fact that an operation was recorded."""

from __future__ import annotations

from datetime import datetime  # noqa: TC003
from typing import Any

from event_sourcing import DomainEvent, event

from syn_domain.contexts.agent_sessions._shared.value_objects import OperationType  # noqa: TC001


@event("OperationRecorded", "v3")
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
    - v3: Added execution_id (issue #1853), copied from the session's
      SessionStarted, so the realtime projection can route the operation to
      its execution's stream. Optional, defaulted, no upcaster: the version
      string is descriptive and ``schema_version`` is unchanged, so stored
      v1/v2 payloads load with ``execution_id=None``.
    """

    # Context
    session_id: str
    operation_id: str
    execution_id: str | None = None  # None for sessions outside an execution, and pre-v3 events

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
