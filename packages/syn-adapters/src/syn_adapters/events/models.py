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

from syn_shared.events import (
    SESSION_COMPLETED,
    SESSION_STARTED,
    SUBAGENT_STARTED,
    SUBAGENT_STOPPED,
    TOKEN_USAGE,
    TOOL_COMPLETED,
    TOOL_STARTED,
    EventType,
)


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
        if isinstance(v, UUID):
            return str(v)
        if isinstance(v, str):
            return v
        return str(v)

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
        from datetime import datetime

        # Get time from data or use default
        time_value = data.get("time") or data.get("timestamp") or datetime.now()

        # Get raw event type
        raw_type = data.get("event_type") or data.get("type", "error")

        # Detect tool events from message content (Claude CLI nests them)
        # assistant + tool_use → tool_execution_started
        # user + tool_result → tool_execution_completed
        message = data.get("message", {})
        content = message.get("content", [])
        inner_type = None
        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict):
                    item_type = item.get("type")
                    if item_type in ("tool_use", "tool_result"):
                        inner_type = item_type
                        break

        # Map Claude CLI event types to normalized types
        # Output values use constants from syn_shared.events for type safety
        event_type_mapping = {
            # Tool events (inner content type takes precedence)
            "tool_started": TOOL_STARTED,
            "tool_use": TOOL_STARTED,
            # Tool results
            "tool_result": TOOL_COMPLETED,
            "tool_completed": TOOL_COMPLETED,
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
        }

        # Use inner_type if it's a tool event, otherwise use raw_type
        type_to_map = inner_type if inner_type else raw_type
        normalized_type = event_type_mapping.get(type_to_map, raw_type)

        # Build data dict from remaining fields
        excluded_keys = {
            "time",
            "timestamp",
            "event_type",
            "type",
            "session_id",
            "execution_id",
            "phase_id",
            "id",
        }
        event_data: dict[str, Any] = {k: v for k, v in data.items() if k not in excluded_keys}

        # Extract tool info from nested Claude CLI message content
        # This handles both tool_use (assistant) and tool_result (user) events
        # Note: message and content were already extracted above for type detection
        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict):
                    item_type = item.get("type")
                    # Extract from tool_use (in assistant messages)
                    if item_type == "tool_use":
                        if "tool_name" not in event_data:
                            event_data["tool_name"] = item.get("name")
                        if "tool_use_id" not in event_data:
                            event_data["tool_use_id"] = item.get("id")
                        if "input_preview" not in event_data:
                            # Store tool input as preview
                            tool_input = item.get("input")
                            if tool_input:
                                event_data["input_preview"] = json.dumps(tool_input)[:500]
                    # Extract from tool_result (in user messages)
                    elif item_type == "tool_result":
                        if "tool_use_id" not in event_data:
                            event_data["tool_use_id"] = item.get("tool_use_id")
                        # tool_name may have been added by enrichment
                        if "tool_name" not in event_data and "tool_name" in item:
                            event_data["tool_name"] = item["tool_name"]
                        # Check success from is_error field
                        if "success" not in event_data:
                            event_data["success"] = not item.get("is_error", False)

        # Normalize field names (only include optional fields if set)
        normalized: dict[str, Any] = {
            "time": time_value,
            "event_type": normalized_type,
            "data": event_data,
        }

        # Only include optional UUID fields if they're set
        if data.get("session_id"):
            normalized["session_id"] = data["session_id"]
        if data.get("execution_id"):
            normalized["execution_id"] = data["execution_id"]
        if data.get("phase_id"):
            normalized["phase_id"] = data["phase_id"]

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
