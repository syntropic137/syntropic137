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

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from aef_shared.events import EventType, VALID_EVENT_TYPES


class AgentEvent(BaseModel):
    """Agent event stored in TimescaleDB.

    All events from agent execution flow through this model:
    - Tool executions (tool_started, tool_completed)
    - Token usage (token_usage)
    - Session lifecycle (session_started, session_completed)
    - Errors (error)

    The model validates types before insertion, catching mismatches
    at runtime rather than letting them fail in the database.

    IMPORTANT: event_type is validated against VALID_EVENT_TYPES.
    If you get a validation error, add the event type to aef_shared.events.
    """

    # Primary key (optional - DB generates)
    id: UUID | None = Field(default=None)

    # Time dimension (required for TimescaleDB hypertable)
    time: datetime = Field(default_factory=datetime.now)

    # Event classification - validated against VALID_EVENT_TYPES
    event_type: EventType = Field(...)

    # Correlation IDs (UUIDs for type safety)
    session_id: UUID | None = Field(default=None)
    execution_id: UUID | None = Field(default=None)
    phase_id: str | None = Field(default=None, max_length=255)

    # Flexible payload
    data: dict[str, Any] = Field(default_factory=dict)

    @field_validator("session_id", "execution_id", mode="before")
    @classmethod
    def parse_uuid(cls, v: str | UUID | None) -> UUID | None:
        """Parse string UUIDs to UUID objects."""
        if v is None:
            return None
        if isinstance(v, UUID):
            return v
        if isinstance(v, str):
            try:
                return UUID(v)
            except ValueError:
                # Invalid UUID string - return None instead of failing
                return None
        return None

    @field_validator("data", mode="before")
    @classmethod
    def ensure_dict(cls, v: Any) -> dict[str, Any]:
        """Ensure data is always a dict."""
        if v is None:
            return {}
        if isinstance(v, dict):
            return v
        return {"value": v}

    def to_insert_tuple(self) -> tuple[datetime, str, UUID | None, UUID | None, str | None, str]:
        """Convert to tuple for asyncpg insert.

        Returns:
            Tuple of (time, event_type, session_id, execution_id, phase_id, data_json)
        """
        import json

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
        """
        from datetime import datetime

        # Get time from data or use default
        time_value = data.get("time") or data.get("timestamp") or datetime.now()

        # Normalize field names (only include optional fields if set)
        normalized: dict[str, Any] = {
            "time": time_value,
            "event_type": data.get("event_type") or data.get("type", "unknown"),
            "data": {
                k: v
                for k, v in data.items()
                if k
                not in (
                    "time",
                    "timestamp",
                    "event_type",
                    "type",
                    "session_id",
                    "execution_id",
                    "phase_id",
                    "id",
                )
            },
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
EXPECTED_COLUMNS = {
    "id": "uuid",
    "time": "timestamp with time zone",
    "event_type": "character varying",
    "session_id": "uuid",
    "execution_id": "uuid",
    "phase_id": "character varying",
    "data": "jsonb",
}
