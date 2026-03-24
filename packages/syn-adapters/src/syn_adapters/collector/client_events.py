"""Collector client tool event helpers.

Extracted from client.py to reduce module complexity.
Handles tool event construction (started, completed, blocked, observation).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from syn_adapters.collector.models import (
    CollectorEvent,
    generate_event_id,
    generate_tool_event_id,
)

if TYPE_CHECKING:
    from syn_adapters.collector.client import CollectorClient

logger = logging.getLogger(__name__)


async def send_tool_started(
    client: CollectorClient,
    session_id: str,
    tool_name: str,
    tool_use_id: str,
    tool_input: dict[str, Any],
    *,
    timestamp: datetime | None = None,
) -> None:
    """Send a tool_execution_started event.

    Args:
        client: CollectorClient instance.
        session_id: Agent session identifier
        tool_name: Name of the tool being executed
        tool_use_id: Claude's tool use identifier
        tool_input: Tool input parameters
        timestamp: Optional timestamp (defaults to now)
    """
    ts = timestamp or datetime.now(UTC)
    event = CollectorEvent(
        event_id=generate_tool_event_id(
            session_id, "tool_execution_started", ts, tool_name, tool_use_id
        ),
        event_type="tool_execution_started",
        session_id=session_id,
        timestamp=ts,
        data={
            "tool_name": tool_name,
            "tool_use_id": tool_use_id,
            "tool_input": tool_input,
        },
    )
    await client.emit(event)
    logger.debug(
        "Queued tool_execution_started: session=%s, tool=%s, tool_use_id=%s",
        session_id,
        tool_name,
        tool_use_id,
    )


async def send_tool_completed(
    client: CollectorClient,
    session_id: str,
    tool_name: str,
    tool_use_id: str,
    duration_ms: int,
    success: bool,
    *,
    error_message: str | None = None,
    timestamp: datetime | None = None,
) -> None:
    """Send a tool_execution_completed event.

    Args:
        client: CollectorClient instance.
        session_id: Agent session identifier
        tool_name: Name of the tool
        tool_use_id: Claude's tool use identifier
        duration_ms: Execution duration in milliseconds
        success: Whether execution succeeded
        error_message: Optional error message if failed
        timestamp: Optional timestamp (defaults to now)
    """
    ts = timestamp or datetime.now(UTC)
    event = CollectorEvent(
        event_id=generate_tool_event_id(
            session_id, "tool_execution_completed", ts, tool_name, tool_use_id
        ),
        event_type="tool_execution_completed",
        session_id=session_id,
        timestamp=ts,
        data={
            "tool_name": tool_name,
            "tool_use_id": tool_use_id,
            "duration_ms": duration_ms,
            "success": success,
            "error_message": error_message,
        },
    )
    await client.emit(event)
    logger.debug(
        "Queued tool_execution_completed: session=%s, tool=%s, duration=%dms, success=%s",
        session_id,
        tool_name,
        duration_ms,
        success,
    )


async def send_tool_blocked(
    client: CollectorClient,
    session_id: str,
    tool_name: str,
    tool_use_id: str,
    reason: str,
    *,
    validator_name: str | None = None,
    timestamp: datetime | None = None,
) -> None:
    """Send a tool_blocked event.

    Args:
        client: CollectorClient instance.
        session_id: Agent session identifier
        tool_name: Name of the tool
        tool_use_id: Claude's tool use identifier
        reason: Why the tool was blocked
        validator_name: Name of the validator that blocked it
        timestamp: Optional timestamp (defaults to now)
    """
    ts = timestamp or datetime.now(UTC)
    event = CollectorEvent(
        event_id=generate_tool_event_id(session_id, "tool_blocked", ts, tool_name, tool_use_id),
        event_type="tool_blocked",
        session_id=session_id,
        timestamp=ts,
        data={
            "tool_name": tool_name,
            "tool_use_id": tool_use_id,
            "reason": reason,
            "validator_name": validator_name,
        },
    )
    await client.emit(event)
    logger.debug(
        "Queued tool_blocked: session=%s, tool=%s, reason=%s",
        session_id,
        tool_name,
        reason,
    )


async def send_observation(client: CollectorClient, event: dict[str, Any]) -> None:
    """Send a generic observation event.

    This is for custom events that don't fit the convenience methods.

    Args:
        client: CollectorClient instance.
        event: Event dictionary with event_type, session_id, data, etc.
    """
    ts = event.get("timestamp") or datetime.now(UTC)
    if isinstance(ts, str):
        ts = datetime.fromisoformat(ts)

    collector_event = CollectorEvent(
        event_id=event.get("event_id")
        or generate_event_id(
            event.get("session_id", "unknown"),
            event.get("event_type", "unknown"),
            ts,
            None,
        ),
        event_type=event.get("event_type", "unknown"),
        session_id=event.get("session_id", "unknown"),
        timestamp=ts,
        data=event.get("data", {}),
    )
    await client.emit(collector_event)
