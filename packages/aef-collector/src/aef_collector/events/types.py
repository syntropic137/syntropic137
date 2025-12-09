"""Event type definitions for AEF collector.

Defines the core event types used throughout the collection system:
- CollectedEvent: Individual event with deterministic ID
- EventBatch: Batched events from a sidecar
- BatchResponse: Response from collector service
"""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 - used at runtime by Pydantic
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class EventType(str, Enum):
    """Event types collected from hooks and transcripts.

    Session lifecycle:
    - SESSION_STARTED: Agent session begins
    - SESSION_ENDED: Agent session ends

    Tool execution:
    - TOOL_EXECUTION_STARTED: Tool call initiated (PreToolUse)
    - TOOL_EXECUTION_COMPLETED: Tool call finished (PostToolUse)
    - TOOL_BLOCKED: Tool call blocked by validation

    User interaction:
    - USER_PROMPT_SUBMITTED: User submitted a prompt

    Token usage:
    - TOKEN_USAGE: Per-turn token metrics from transcript

    Context management:
    - PRE_COMPACT: Context compaction triggered
    """

    # Session lifecycle
    SESSION_STARTED = "session_started"
    SESSION_ENDED = "session_ended"

    # Tool execution
    TOOL_EXECUTION_STARTED = "tool_execution_started"
    TOOL_EXECUTION_COMPLETED = "tool_execution_completed"
    TOOL_BLOCKED = "tool_blocked"

    # User interaction
    USER_PROMPT_SUBMITTED = "user_prompt_submitted"

    # Token usage
    TOKEN_USAGE = "token_usage"

    # Context management
    PRE_COMPACT = "pre_compact"


class CollectedEvent(BaseModel):
    """A single collected event with deterministic ID.

    The event_id is generated deterministically from content
    to enable deduplication across retries.

    Attributes:
        event_id: Deterministic ID for deduplication (SHA256 hash)
        event_type: Type of event (from EventType enum)
        session_id: Agent session identifier
        timestamp: When the event occurred (ISO 8601)
        data: Event-specific payload
    """

    event_id: str = Field(
        ...,
        description="Deterministic ID for deduplication",
        min_length=16,
        max_length=64,
    )
    event_type: EventType = Field(..., description="Type of event")
    session_id: str = Field(..., description="Agent session identifier")
    timestamp: datetime = Field(..., description="When the event occurred")
    data: dict[str, Any] = Field(default_factory=dict, description="Event-specific payload")

    model_config = {"frozen": True}


class EventBatch(BaseModel):
    """Batch of events from a sidecar.

    Events are batched to reduce network overhead.
    The batch_id is used for idempotent processing.

    Attributes:
        agent_id: Identifier for the agent sending events
        batch_id: Unique identifier for this batch
        events: List of collected events
    """

    agent_id: str = Field(..., description="Agent sending the batch")
    batch_id: str = Field(..., description="Unique batch identifier")
    events: list[CollectedEvent] = Field(
        default_factory=list,
        description="Events in this batch",
    )


class BatchResponse(BaseModel):
    """Response from collector after processing a batch.

    Includes counts of accepted and duplicate events for observability.

    Attributes:
        accepted: Number of events successfully accepted
        duplicates: Number of duplicate events skipped
        batch_id: Echo of the batch_id for correlation
    """

    accepted: int = Field(..., ge=0, description="Events successfully accepted")
    duplicates: int = Field(..., ge=0, description="Duplicate events skipped")
    batch_id: str = Field(..., description="Batch ID for correlation")
