"""Pydantic models and ID generation for Collector observation events.

Extracted from collector/client.py to reduce module complexity.
These models define the wire format for events sent to the Collector service.

See: ADR-017, ADR-018
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class CollectorEvent(BaseModel):
    """A single observation event to send to the Collector.

    Attributes:
        event_id: Deterministic ID for deduplication (SHA256 hash)
        event_type: Type of event (e.g., "tool_execution_started")
        session_id: Agent session identifier
        timestamp: When the event occurred (ISO 8601)
        data: Event-specific payload
    """

    event_id: str = Field(..., description="Deterministic ID for deduplication")
    event_type: str = Field(..., description="Type of event")
    session_id: str = Field(..., description="Agent session identifier")
    timestamp: datetime = Field(..., description="When the event occurred")
    data: dict[str, Any] = Field(default_factory=dict, description="Event payload")

    model_config = {"frozen": True}


class EventBatch(BaseModel):
    """Batch of events to send to Collector."""

    agent_id: str = Field(..., description="Agent sending the batch")
    batch_id: str = Field(..., description="Unique batch identifier")
    events: list[CollectorEvent] = Field(default_factory=list, description="Events in batch")


class BatchResponse(BaseModel):
    """Response from Collector after processing a batch."""

    accepted: int = Field(..., ge=0, description="Events successfully accepted")
    duplicates: int = Field(..., ge=0, description="Duplicate events skipped")
    batch_id: str = Field(..., description="Batch ID for correlation")


def generate_event_id(
    session_id: str,
    event_type: str,
    timestamp: datetime,
    content_hash: str | None = None,
) -> str:
    """Generate deterministic event ID for deduplication.

    Same inputs always produce the same event_id.

    Args:
        session_id: Agent session identifier
        event_type: Type of event
        timestamp: When the event occurred
        content_hash: Optional hash of event-specific content

    Returns:
        32-character hex string (truncated SHA256)
    """
    key_parts = [session_id, event_type, timestamp.isoformat()]
    if content_hash:
        key_parts.append(content_hash)
    key = "|".join(key_parts)
    return hashlib.sha256(key.encode()).hexdigest()[:32]


def generate_tool_event_id(
    session_id: str,
    event_type: str,
    timestamp: datetime,
    tool_name: str,
    tool_use_id: str,
) -> str:
    """Generate event ID for tool execution events.

    Args:
        session_id: Agent session identifier
        event_type: Type of tool event (started/completed/blocked)
        timestamp: When the event occurred
        tool_name: Name of the tool
        tool_use_id: Claude's tool use identifier

    Returns:
        32-character hex string
    """
    content = f"{tool_name}|{tool_use_id}"
    content_hash = hashlib.sha256(content.encode()).hexdigest()[:16]
    return generate_event_id(session_id, event_type, timestamp, content_hash)
