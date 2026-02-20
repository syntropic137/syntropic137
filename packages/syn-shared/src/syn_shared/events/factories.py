"""Type-safe event factories for tests.

Use these instead of raw dicts to get:
- Type checking on field names
- Required vs optional field enforcement
- IDE autocomplete
- Schema changes caught at type-check time

Usage in tests:
    from syn_shared.events.factories import tool_started, session_started

    event = tool_started(
        session_id="test-session",
        tool_name="Read",
        tool_use_id="tool-1",
    )

If the schema changes (e.g., tool_name -> name), mypy will catch it.
"""

from __future__ import annotations

from typing import Any, TypedDict

from syn_shared.events import (
    SESSION_COMPLETED,
    SESSION_STARTED,
    TOKEN_USAGE,
    TOOL_EXECUTION_COMPLETED,
    TOOL_EXECUTION_STARTED,
)

# =============================================================================
# TypedDict schemas for event payloads
# =============================================================================


class ToolStartedPayload(TypedDict, total=False):
    """Payload for tool_execution_started events."""

    tool_name: str  # Required
    tool_use_id: str  # Required
    input_preview: str  # Optional


class ToolCompletedPayload(TypedDict, total=False):
    """Payload for tool_execution_completed events."""

    tool_name: str  # Required
    tool_use_id: str  # Required
    success: bool  # Required
    duration_ms: int  # Optional
    error: str  # Optional (only if success=False)


class SessionStartedPayload(TypedDict, total=False):
    """Payload for session_started events."""

    provider: str  # Optional (e.g., "claude", "openai")
    model: str  # Optional


class SessionCompletedPayload(TypedDict, total=False):
    """Payload for session_completed events."""

    exit_code: int  # Optional
    duration_ms: int  # Optional


class TokenUsagePayload(TypedDict, total=False):
    """Payload for token_usage events."""

    input_tokens: int  # Required
    output_tokens: int  # Required
    cache_creation_tokens: int  # Optional
    cache_read_tokens: int  # Optional


# =============================================================================
# Event factory functions
# =============================================================================


def tool_started(
    *,
    session_id: str,
    tool_name: str,
    tool_use_id: str,
    execution_id: str | None = None,
    input_preview: str | None = None,
) -> dict[str, Any]:
    """Create a tool_execution_started event.

    Args:
        session_id: Session identifier (required)
        tool_name: Name of the tool being executed (required)
        tool_use_id: Unique ID for this tool invocation (required)
        execution_id: Workflow execution ID (optional)
        input_preview: Truncated input for debugging (optional)

    Returns:
        Event dict ready for insert_batch()
    """
    event: dict[str, Any] = {
        "event_type": TOOL_EXECUTION_STARTED,
        "session_id": session_id,
        "tool_name": tool_name,
        "tool_use_id": tool_use_id,
    }
    if execution_id:
        event["execution_id"] = execution_id
    if input_preview:
        event["input_preview"] = input_preview
    return event


def tool_completed(
    *,
    session_id: str,
    tool_name: str,
    tool_use_id: str,
    success: bool,
    execution_id: str | None = None,
    duration_ms: int | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    """Create a tool_execution_completed event.

    Args:
        session_id: Session identifier (required)
        tool_name: Name of the tool (required)
        tool_use_id: Unique ID matching the started event (required)
        success: Whether the tool succeeded (required)
        execution_id: Workflow execution ID (optional)
        duration_ms: Execution time in milliseconds (optional)
        error: Error message if success=False (optional)

    Returns:
        Event dict ready for insert_batch()
    """
    event: dict[str, Any] = {
        "event_type": TOOL_EXECUTION_COMPLETED,
        "session_id": session_id,
        "tool_name": tool_name,
        "tool_use_id": tool_use_id,
        "success": success,
    }
    if execution_id:
        event["execution_id"] = execution_id
    if duration_ms is not None:
        event["duration_ms"] = duration_ms
    if error:
        event["error"] = error
    return event


def session_started(
    *,
    session_id: str,
    execution_id: str | None = None,
    provider: str | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    """Create a session_started event.

    Args:
        session_id: Session identifier (required)
        execution_id: Workflow execution ID (optional)
        provider: LLM provider name (optional, e.g., "claude")
        model: Model name (optional, e.g., "claude-3-opus")

    Returns:
        Event dict ready for insert_batch()
    """
    event: dict[str, Any] = {
        "event_type": SESSION_STARTED,
        "session_id": session_id,
    }
    if execution_id:
        event["execution_id"] = execution_id
    if provider:
        event["provider"] = provider
    if model:
        event["model"] = model
    return event


def session_completed(
    *,
    session_id: str,
    execution_id: str | None = None,
    exit_code: int | None = None,
    duration_ms: int | None = None,
) -> dict[str, Any]:
    """Create a session_completed event.

    Args:
        session_id: Session identifier (required)
        execution_id: Workflow execution ID (optional)
        exit_code: Process exit code (optional)
        duration_ms: Total session time in milliseconds (optional)

    Returns:
        Event dict ready for insert_batch()
    """
    event: dict[str, Any] = {
        "event_type": SESSION_COMPLETED,
        "session_id": session_id,
    }
    if execution_id:
        event["execution_id"] = execution_id
    if exit_code is not None:
        event["exit_code"] = exit_code
    if duration_ms is not None:
        event["duration_ms"] = duration_ms
    return event


def token_usage(
    *,
    session_id: str,
    input_tokens: int,
    output_tokens: int,
    execution_id: str | None = None,
    cache_creation_tokens: int | None = None,
    cache_read_tokens: int | None = None,
) -> dict[str, Any]:
    """Create a token_usage event.

    Args:
        session_id: Session identifier (required)
        input_tokens: Number of input tokens (required)
        output_tokens: Number of output tokens (required)
        execution_id: Workflow execution ID (optional)
        cache_creation_tokens: Tokens used to create cache (optional)
        cache_read_tokens: Tokens read from cache (optional)

    Returns:
        Event dict ready for insert_batch()
    """
    event: dict[str, Any] = {
        "event_type": TOKEN_USAGE,
        "session_id": session_id,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
    }
    if execution_id:
        event["execution_id"] = execution_id
    if cache_creation_tokens is not None:
        event["cache_creation_tokens"] = cache_creation_tokens
    if cache_read_tokens is not None:
        event["cache_read_tokens"] = cache_read_tokens
    return event


__all__ = [
    # TypedDict schemas (for type hints)
    "SessionCompletedPayload",
    "SessionStartedPayload",
    "TokenUsagePayload",
    "ToolCompletedPayload",
    "ToolStartedPayload",
    # Factory functions
    "session_completed",
    "session_started",
    "token_usage",
    "tool_completed",
    "tool_started",
]
