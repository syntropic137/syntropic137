"""Convenience factory functions for creating operation commands.

These functions provide type-safe ways to create RecordOperationCommand
for specific operation types, ensuring the correct fields are populated.
"""

from __future__ import annotations

from typing import Any

from syn_domain.contexts.agent_sessions._shared.value_objects import OperationType
from syn_domain.contexts.agent_sessions.domain.commands.RecordOperationCommand import (
    RecordOperationCommand,
)


def record_tool_started(
    session_id: str,
    tool_name: str,
    tool_use_id: str,
    tool_input: dict[str, Any] | None = None,
) -> RecordOperationCommand:
    """Create command to record a tool invocation start.

    Args:
        session_id: The session to record the operation in.
        tool_name: Name of the tool being invoked (e.g., "Read", "Write", "Bash").
        tool_use_id: Unique ID for this tool invocation (correlates with completed).
        tool_input: Input parameters passed to the tool.

    Returns:
        RecordOperationCommand configured for TOOL_STARTED.
    """
    return RecordOperationCommand(
        aggregate_id=session_id,
        operation_type=OperationType.TOOL_STARTED,
        tool_name=tool_name,
        tool_use_id=tool_use_id,
        tool_input=tool_input,
    )


def record_tool_completed(
    session_id: str,
    tool_name: str,
    tool_use_id: str,
    tool_output: str | None = None,
    duration_seconds: float | None = None,
    success: bool = True,
) -> RecordOperationCommand:
    """Create command to record a tool invocation completion.

    Args:
        session_id: The session to record the operation in.
        tool_name: Name of the tool that completed.
        tool_use_id: Unique ID for this tool invocation (correlates with started).
        tool_output: Output from the tool (truncated if large).
        duration_seconds: How long the tool took to execute.
        success: Whether the tool completed successfully.

    Returns:
        RecordOperationCommand configured for TOOL_COMPLETED.
    """
    return RecordOperationCommand(
        aggregate_id=session_id,
        operation_type=OperationType.TOOL_COMPLETED,
        tool_name=tool_name,
        tool_use_id=tool_use_id,
        tool_output=tool_output,
        duration_seconds=duration_seconds,
        success=success,
    )


def record_tool_blocked(
    session_id: str,
    tool_name: str,
    tool_use_id: str,
    reason: str,
    validator: str | None = None,
) -> RecordOperationCommand:
    """Create command to record a blocked tool invocation.

    Args:
        session_id: The session to record the operation in.
        tool_name: Name of the tool that was blocked.
        tool_use_id: Unique ID for this tool invocation.
        reason: Why the tool was blocked.
        validator: Which validator blocked the tool (optional).

    Returns:
        RecordOperationCommand configured for TOOL_BLOCKED.
    """
    return RecordOperationCommand(
        aggregate_id=session_id,
        operation_type=OperationType.TOOL_BLOCKED,
        tool_name=tool_name,
        tool_use_id=tool_use_id,
        success=False,
        metadata={"reason": reason, "validator": validator} if validator else {"reason": reason},
    )


def record_message_request(
    session_id: str,
    role: str,
    content: str | None = None,
    input_tokens: int | None = None,
) -> RecordOperationCommand:
    """Create command to record a message request to the LLM.

    Args:
        session_id: The session to record the operation in.
        role: Message role (user, system).
        content: Message content (truncated if large).
        input_tokens: Number of input tokens for this message.

    Returns:
        RecordOperationCommand configured for MESSAGE_REQUEST.
    """
    return RecordOperationCommand(
        aggregate_id=session_id,
        operation_type=OperationType.MESSAGE_REQUEST,
        message_role=role,
        message_content=content,
        input_tokens=input_tokens,
    )


def record_message_response(
    session_id: str,
    content: str | None = None,
    output_tokens: int | None = None,
    input_tokens: int | None = None,
    total_tokens: int | None = None,
) -> RecordOperationCommand:
    """Create command to record a message response from the LLM.

    Args:
        session_id: The session to record the operation in.
        content: Response content (truncated if large).
        output_tokens: Number of output tokens in this response.
        input_tokens: Number of input tokens (if reported).
        total_tokens: Total tokens for this turn.

    Returns:
        RecordOperationCommand configured for MESSAGE_RESPONSE.
    """
    return RecordOperationCommand(
        aggregate_id=session_id,
        operation_type=OperationType.MESSAGE_RESPONSE,
        message_role="assistant",
        message_content=content,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
    )


def record_thinking(
    session_id: str,
    content: str,
) -> RecordOperationCommand:
    """Create command to record extended thinking content.

    Args:
        session_id: The session to record the operation in.
        content: Thinking content (truncated if large).

    Returns:
        RecordOperationCommand configured for THINKING.
    """
    return RecordOperationCommand(
        aggregate_id=session_id,
        operation_type=OperationType.THINKING,
        thinking_content=content,
    )


def record_error(
    session_id: str,
    error_message: str,
    error_type: str | None = None,
) -> RecordOperationCommand:
    """Create command to record an error.

    Args:
        session_id: The session to record the operation in.
        error_message: The error message.
        error_type: Type of error (e.g., "timeout", "api_error").

    Returns:
        RecordOperationCommand configured for ERROR.
    """
    metadata: dict[str, Any] = {"error_message": error_message}
    if error_type:
        metadata["error_type"] = error_type

    return RecordOperationCommand(
        aggregate_id=session_id,
        operation_type=OperationType.ERROR,
        success=False,
        metadata=metadata,
    )
