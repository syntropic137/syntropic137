"""Event type definitions for Syn137 collector.

Defines the core event types used throughout the collection system:
- CollectedEvent: Individual event with deterministic ID
- EventBatch: Batched events from a sidecar
- BatchResponse: Response from collector service
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class EventType(StrEnum):
    """Event types collected from hooks and transcripts.

    Session lifecycle:
    - SESSION_STARTED: Agent session begins
    - SESSION_ENDED: Agent session ends
    - AGENT_STOPPED: Agent stopped (normal completion or interrupt)
    - SUBAGENT_STOPPED: Subagent completed

    Tool execution:
    - TOOL_EXECUTION_STARTED: Tool call initiated (PreToolUse)
    - TOOL_EXECUTION_COMPLETED: Tool call finished (PostToolUse)
    - TOOL_BLOCKED: Tool call blocked by validation

    User interaction:
    - USER_PROMPT_SUBMITTED: User submitted a prompt
    - NOTIFICATION_SENT: Notification sent to user

    Token usage:
    - TOKEN_USAGE: Per-turn token metrics from transcript

    Context management:
    - PRE_COMPACT: Context compaction triggered

    Git operations:
    - GIT_COMMIT: Git commit completed with metrics
    - GIT_BRANCH_CREATED: New branch created
    - GIT_BRANCH_SWITCHED: Switched to existing branch
    - GIT_MERGE_COMPLETED: Merge completed
    - GIT_COMMITS_REWRITTEN: Commits rewritten (rebase/amend)
    - GIT_PUSH_STARTED: Push operation started
    - GIT_PUSH_COMPLETED: Push operation completed

    Workspace lifecycle (isolated sandbox environments):
    - WORKSPACE_CREATING: Workspace creation started
    - WORKSPACE_CREATED: Workspace ready for use
    - WORKSPACE_COMMAND_EXECUTED: Command executed in workspace
    - WORKSPACE_DESTROYING: Workspace cleanup started
    - WORKSPACE_DESTROYED: Workspace fully cleaned up
    - WORKSPACE_ERROR: Workspace operation failed

    OTLP-sourced events (OTel channel — from workspace containers):
    - OTLP_LOG: Raw OTel log record (unrecognised event name)
    - API_REQUEST: Per-API-call metrics (model, cost, cache tokens, duration)
    - API_ERROR: API error with status code and retry count
    - OTLP_SESSION_COUNT: OTel session counter (distinct from hook SESSION_STARTED)
    - OTLP_COMMIT_COUNT: OTel commit counter (distinct from hook GIT_COMMIT)
    """

    # Session lifecycle
    SESSION_STARTED = "session_started"
    SESSION_ENDED = "session_ended"
    AGENT_STOPPED = "agent_stopped"
    SUBAGENT_STARTED = "subagent_started"
    SUBAGENT_STOPPED = "subagent_stopped"

    # Tool execution
    TOOL_EXECUTION_STARTED = "tool_execution_started"
    TOOL_EXECUTION_COMPLETED = "tool_execution_completed"
    TOOL_BLOCKED = "tool_blocked"

    # User interaction
    USER_PROMPT_SUBMITTED = "user_prompt_submitted"
    NOTIFICATION_SENT = "notification_sent"

    # Token usage
    TOKEN_USAGE = "token_usage"

    # Context management
    PRE_COMPACT = "pre_compact"

    # Git operations
    GIT_COMMIT = "git_commit"
    GIT_BRANCH_CREATED = "git_branch_created"
    GIT_BRANCH_SWITCHED = "git_branch_switched"
    GIT_MERGE_COMPLETED = "git_merge_completed"
    GIT_COMMITS_REWRITTEN = "git_commits_rewritten"
    GIT_PUSH_STARTED = "git_push_started"
    GIT_PUSH_COMPLETED = "git_push_completed"

    # Workspace lifecycle (isolated sandbox environments)
    WORKSPACE_CREATING = "workspace_creating"
    WORKSPACE_CREATED = "workspace_created"
    WORKSPACE_COMMAND_EXECUTED = "workspace_command_executed"
    WORKSPACE_DESTROYING = "workspace_destroying"
    WORKSPACE_DESTROYED = "workspace_destroyed"
    WORKSPACE_ERROR = "workspace_error"

    # Cost tracking
    COST_RECORDED = "cost_recorded"
    SESSION_COST_FINALIZED = "session_cost_finalized"

    # OTLP-sourced events
    OTLP_LOG = "otlp_log"
    API_REQUEST = "api_request"  # Per-API-call cost, model, cache tokens, duration
    API_ERROR = "api_error"  # API error with status code and retry context
    OTLP_SESSION_COUNT = (
        "otlp_session_count"  # OTel session counter (distinct from hook session_started)
    )
    OTLP_COMMIT_COUNT = "otlp_commit_count"  # OTel commit counter (distinct from hook git_commit)


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
