"""Event types and emission for agent runner.

Events are emitted as JSONL (one JSON object per line) to stdout.
The orchestrator parses these to update the workflow aggregate.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any


class EventType(str, Enum):
    """Types of events emitted by the agent runner."""

    # Lifecycle events
    STARTED = "started"
    COMPLETED = "completed"
    ERROR = "error"
    CANCELLED = "cancelled"

    # Progress events
    PROGRESS = "progress"
    TURN_START = "turn_start"
    TURN_END = "turn_end"

    # Tool events
    TOOL_USE = "tool_use"
    TOOL_RESULT = "tool_result"

    # Artifact events
    ARTIFACT = "artifact"

    # Token events
    TOKEN_USAGE = "token_usage"


@dataclass
class AgentEvent:
    """Base event emitted by the agent runner.

    All events include:
    - type: The event type
    - timestamp: ISO-8601 timestamp
    - Additional type-specific data
    """

    type: EventType
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        result = {
            "type": self.type.value,
            "timestamp": self.timestamp,
        }
        result.update(self.data)
        return result

    def to_json(self) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict())


def emit_event(event: AgentEvent | dict[str, Any]) -> None:
    """Emit an event to stdout as JSONL.

    Args:
        event: AgentEvent instance or dict with event data
    """
    if isinstance(event, AgentEvent):
        line = event.to_json()
    else:
        # Ensure timestamp if not present
        if "timestamp" not in event:
            event["timestamp"] = datetime.now(UTC).isoformat()
        line = json.dumps(event)

    # Print to stdout with flush for real-time streaming
    print(line, flush=True)


# Convenience functions for common events


def emit_started() -> None:
    """Emit a started event."""
    emit_event(AgentEvent(type=EventType.STARTED))


def emit_completed(success: bool, duration_ms: int | None = None) -> None:
    """Emit a completed event."""
    data: dict[str, Any] = {"success": success}
    if duration_ms is not None:
        data["duration_ms"] = duration_ms
    emit_event(AgentEvent(type=EventType.COMPLETED, data=data))


def emit_error(message: str, error_type: str | None = None) -> None:
    """Emit an error event."""
    data: dict[str, Any] = {"message": message}
    if error_type:
        data["error_type"] = error_type
    emit_event(AgentEvent(type=EventType.ERROR, data=data))


def emit_cancelled() -> None:
    """Emit a cancelled event."""
    emit_event(AgentEvent(type=EventType.CANCELLED))


def emit_progress(
    turn: int,
    input_tokens: int = 0,
    output_tokens: int = 0,
) -> None:
    """Emit a progress event."""
    emit_event(
        AgentEvent(
            type=EventType.PROGRESS,
            data={
                "turn": turn,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
            },
        )
    )


def emit_tool_use(
    tool_name: str,
    tool_input: dict[str, Any] | None = None,
    tool_use_id: str | None = None,
) -> None:
    """Emit a tool_use event."""
    data: dict[str, Any] = {"tool": tool_name}
    if tool_input:
        data["input"] = tool_input
    if tool_use_id:
        data["tool_use_id"] = tool_use_id
    emit_event(AgentEvent(type=EventType.TOOL_USE, data=data))


def emit_tool_result(
    tool_name: str,
    success: bool,
    tool_use_id: str | None = None,
    duration_ms: int | None = None,
) -> None:
    """Emit a tool_result event."""
    data: dict[str, Any] = {"tool": tool_name, "success": success}
    if tool_use_id:
        data["tool_use_id"] = tool_use_id
    if duration_ms is not None:
        data["duration_ms"] = duration_ms
    emit_event(AgentEvent(type=EventType.TOOL_RESULT, data=data))


def emit_artifact(name: str, path: str, size_bytes: int | None = None) -> None:
    """Emit an artifact event."""
    data: dict[str, Any] = {"name": name, "path": path}
    if size_bytes is not None:
        data["size_bytes"] = size_bytes
    emit_event(AgentEvent(type=EventType.ARTIFACT, data=data))


def emit_token_usage(
    input_tokens: int,
    output_tokens: int,
    cache_creation_tokens: int = 0,
    cache_read_tokens: int = 0,
) -> None:
    """Emit a token_usage event."""
    emit_event(
        AgentEvent(
            type=EventType.TOKEN_USAGE,
            data={
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cache_creation_tokens": cache_creation_tokens,
                "cache_read_tokens": cache_read_tokens,
            },
        )
    )
