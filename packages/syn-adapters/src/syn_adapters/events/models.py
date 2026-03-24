"""Type-safe models for agent events.

Using Pydantic for type safety and validation. The actual database
operations use asyncpg for performance, but all data passes through
these models for validation.

Note: We use plain Pydantic instead of SQLModel table=True because:
1. We use asyncpg directly for performance (not SQLAlchemy async)
2. dict fields don't work with SQLModel table=True
3. We need TimescaleDB-specific features (hypertables, compression)

See ADR-029: Simplified Event System
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from syn_adapters.events.model_extractors import (
    _extract_tool_result,
    _extract_tool_use,
)
from syn_shared.events import (
    AGENT_STOPPED,
    CONTEXT_COMPACTED,
    GIT_BRANCH_CHANGED,
    GIT_COMMIT,
    GIT_OPERATION,
    GIT_PUSH,
    PERMISSION_REQUESTED,
    SECURITY_DECISION,
    SESSION_COMPLETED,
    SESSION_STARTED,
    SUBAGENT_STARTED,
    SUBAGENT_STOPPED,
    SYSTEM_NOTIFICATION,
    TASK_COMPLETED,
    TEAMMATE_IDLE,
    TOKEN_USAGE,
    TOOL_EXECUTION_COMPLETED,
    TOOL_EXECUTION_FAILED,
    TOOL_EXECUTION_STARTED,
    USER_PROMPT_SUBMITTED,
    EventType,
)


# Map Claude CLI event types to normalized types.
# Output values use constants from syn_shared.events for type safety.
_EVENT_TYPE_MAPPING: dict[str, str] = {
    # Tool events (inner content type takes precedence)
    "tool_started": TOOL_EXECUTION_STARTED,
    "tool_use": TOOL_EXECUTION_STARTED,
    # Tool results
    "tool_result": TOOL_EXECUTION_COMPLETED,
    "tool_completed": TOOL_EXECUTION_COMPLETED,
    # Session lifecycle
    "system.init": SESSION_STARTED,
    "system": SESSION_STARTED,
    "result": SESSION_COMPLETED,
    # Content events map to token_usage (only if not tool events)
    "assistant": TOKEN_USAGE,
    "user": TOKEN_USAGE,
    # Subagent lifecycle events (from EventParser, pass through as-is)
    SUBAGENT_STARTED: SUBAGENT_STARTED,
    SUBAGENT_STOPPED: SUBAGENT_STOPPED,
    # Git observability events (from agentic-primitives observability plugin)
    GIT_COMMIT: GIT_COMMIT,
    GIT_PUSH: GIT_PUSH,
    GIT_BRANCH_CHANGED: GIT_BRANCH_CHANGED,
    GIT_OPERATION: GIT_OPERATION,
    # Claude Code hook events (observability plugin)
    TOOL_EXECUTION_FAILED: TOOL_EXECUTION_FAILED,
    TEAMMATE_IDLE: TEAMMATE_IDLE,
    TASK_COMPLETED: TASK_COMPLETED,
    # Security / permission events (from agentic_events.EventType)
    SECURITY_DECISION: SECURITY_DECISION,
    PERMISSION_REQUESTED: PERMISSION_REQUESTED,
    # Agent control events (from agentic_events.EventType)
    AGENT_STOPPED: AGENT_STOPPED,
    # Context management events (from agentic_events.EventType)
    CONTEXT_COMPACTED: CONTEXT_COMPACTED,
    # System / notification events (from agentic_events.EventType)
    SYSTEM_NOTIFICATION: SYSTEM_NOTIFICATION,
    # User interaction events (from agentic_events.EventType)
    USER_PROMPT_SUBMITTED: USER_PROMPT_SUBMITTED,
}

# Fields excluded from the data dict (they go in top-level AgentEvent fields)
_EXCLUDED_KEYS = {
    "time",
    "timestamp",
    "event_type",
    "type",
    "session_id",
    "execution_id",
    "phase_id",
    "id",
}


def _detect_inner_type(content: list[Any]) -> str | None:
    """Detect tool event type from nested message content.

    Claude CLI nests tool_use/tool_result inside message content arrays.
    Returns the inner type if found, None otherwise.
    """
    for item in content:
        if isinstance(item, dict):
            item_type = item.get("type")
            if item_type in ("tool_use", "tool_result"):
                return item_type
    return None


_TOOL_CONTENT_EXTRACTORS: dict[str, Any] = {
    "tool_use": _extract_tool_use,
    "tool_result": _extract_tool_result,
}


def _extract_tool_data(content: list[Any], event_data: dict[str, Any]) -> None:
    """Extract tool info from nested Claude CLI message content.

    Handles both tool_use (assistant messages) and tool_result (user messages).
    Mutates event_data in place with extracted fields.
    """
    for item in content:
        if isinstance(item, dict):
            extractor = _TOOL_CONTENT_EXTRACTORS.get(item.get("type", ""))
            if extractor:
                extractor(item, event_data)


def _resolve_event_type(data: dict[str, Any], raw_type: str) -> str:
    """Resolve raw event type to normalized type, checking nested content first."""
    message = data.get("message", {})
    content = message.get("content", [])
    inner_type = _detect_inner_type(content) if isinstance(content, list) else None
    type_to_map = inner_type if inner_type else raw_type
    return _EVENT_TYPE_MAPPING.get(type_to_map, raw_type)


class AgentEvent(BaseModel):
    """Agent event stored in TimescaleDB.

    All events from agent execution flow through this model:
    - Tool executions (tool_started, tool_completed)
    - Token usage (token_usage)
    - Session lifecycle (session_started, session_completed)
    - Subagent lifecycle (subagent_started, subagent_stopped)
    - Errors (error)

    The model validates types before insertion, catching mismatches
    at runtime rather than letting them fail in the database.

    IMPORTANT: event_type is validated against VALID_EVENT_TYPES.
    If you get a validation error, add the event type to syn_shared.events.
    """

    # Time dimension (required for TimescaleDB hypertable)
    time: datetime = Field(default_factory=datetime.now)

    # Event classification - validated against VALID_EVENT_TYPES
    event_type: EventType = Field(...)

    # Correlation IDs (text - simpler schema, matches migration 002_agent_events.sql)
    session_id: str | None = Field(default=None)
    execution_id: str | None = Field(default=None)
    phase_id: str | None = Field(default=None)

    # Flexible payload
    data: dict[str, Any] = Field(default_factory=dict)

    @field_validator("session_id", "execution_id", "phase_id", mode="before")
    @classmethod
    def ensure_string(cls, v: str | UUID | None) -> str | None:
        """Convert UUID objects to strings if needed."""
        if v is None:
            return None
        return v if isinstance(v, str) else str(v)

    @field_validator("data", mode="before")
    @classmethod
    def ensure_dict(cls, v: Any) -> dict[str, Any]:
        """Ensure data is always a dict."""
        if v is None:
            return {}
        if isinstance(v, dict):
            return v
        return {"value": v}

    def to_insert_tuple(self) -> tuple[datetime, str, str | None, str | None, str | None, str]:
        """Convert to tuple for asyncpg insert.

        Returns:
            Tuple of (time, event_type, session_id, execution_id, phase_id, data_json)
        """
        return (
            self.time,
            self.event_type,
            self.session_id,
            self.execution_id,
            self.phase_id,
            json.dumps(self.data),
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AgentEvent:
        """Create from raw event dict.

        Handles common field name variations:
        - 'timestamp' -> 'time'
        - 'type' -> 'event_type'

        Maps raw Claude CLI event types to normalized types:
        - 'tool_started' / 'tool_use' -> 'tool_execution_started'
        - 'tool_result' / 'tool_completed' -> 'tool_execution_completed'
        - 'system.init' / 'system' -> 'session_started'
        - 'result' -> 'session_completed'
        - 'assistant' / 'user' -> 'token_usage' (they contain content)
        """
        time_value = data.get("time") or data.get("timestamp") or datetime.now()
        raw_type = data.get("event_type") or data.get("type", "error")
        normalized_type = _resolve_event_type(data, raw_type)

        # Build data dict from remaining fields
        event_data: dict[str, Any] = {k: v for k, v in data.items() if k not in _EXCLUDED_KEYS}

        # Extract tool info from nested content
        content = data.get("message", {}).get("content", [])
        if isinstance(content, list):
            _extract_tool_data(content, event_data)

        normalized: dict[str, Any] = {
            "time": time_value,
            "event_type": normalized_type,
            "data": event_data,
        }
        # Only include optional UUID fields if set
        for field in ("session_id", "execution_id", "phase_id"):
            if data.get(field):
                normalized[field] = data[field]

        return cls(**normalized)


# Schema for validation (used to check DB matches model)
# Must match: packages/syn-adapters/src/syn_adapters/projection_stores/migrations/002_agent_events.sql
EXPECTED_COLUMNS = {
    "time": "timestamp with time zone",
    "event_type": "text",
    "session_id": "text",
    "execution_id": "text",
    "phase_id": "text",
    "data": "jsonb",
}
