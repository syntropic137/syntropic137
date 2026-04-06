"""Deterministic event ID generation for deduplication.

Event IDs are generated from content hashes to enable:
- Deduplication: Same event produces same ID
- Idempotency: Retries don't create duplicates
- Consistency: IDs are reproducible across systems
"""

from __future__ import annotations

import hashlib
from datetime import datetime


def generate_event_id(
    session_id: str,
    event_type: str,
    timestamp: datetime,
    content_hash: str | None = None,
) -> str:
    """Generate deterministic event ID for deduplication.

    Creates a SHA256 hash from the event's identifying components.
    Same inputs always produce the same event_id.

    Args:
        session_id: Agent session identifier
        event_type: Type of event (e.g., "tool_execution_started")
        timestamp: When the event occurred
        content_hash: Optional hash of event-specific content

    Returns:
        32-character hex string (truncated SHA256)

    Example:
        >>> from datetime import datetime
        >>> generate_event_id("session-abc", "tool_started", datetime(2025, 1, 1))
        'a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6'
    """
    key_parts = [
        session_id,
        event_type,
        timestamp.isoformat(),
    ]
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

    Tool events are identified by their tool_use_id from Claude,
    which is unique per tool invocation.

    Args:
        session_id: Agent session identifier
        event_type: Type of tool event (started/completed/blocked)
        timestamp: When the event occurred
        tool_name: Name of the tool (e.g., "Read", "Write")
        tool_use_id: Claude's tool use identifier

    Returns:
        32-character hex string
    """
    content = f"{tool_name}|{tool_use_id}"
    content_hash = hashlib.sha256(content.encode()).hexdigest()[:16]
    return generate_event_id(session_id, event_type, timestamp, content_hash)


def generate_token_event_id(
    session_id: str,
    timestamp: datetime,
    message_uuid: str,
) -> str:
    """Generate event ID for token usage events.

    Token events are identified by the message UUID from Claude's
    transcript, which is unique per assistant turn.

    Args:
        session_id: Agent session identifier
        timestamp: When the event occurred
        message_uuid: UUID of the message from transcript

    Returns:
        32-character hex string
    """
    return generate_event_id(
        session_id,
        "token_usage",
        timestamp,
        message_uuid[:16],
    )


def generate_session_event_id(
    session_id: str,
    event_type: str,
    timestamp: datetime,
) -> str:
    """Generate event ID for session lifecycle events.

    Session events (started/ended) are identified by session_id
    and timestamp alone, as there's no additional content.

    Args:
        session_id: Agent session identifier
        event_type: Type of session event (started/ended)
        timestamp: When the event occurred

    Returns:
        32-character hex string
    """
    return generate_event_id(session_id, event_type, timestamp, None)


def generate_user_prompt_event_id(
    session_id: str,
    timestamp: datetime,
    prompt_hash: str,
) -> str:
    """Generate event ID for user prompt events.

    User prompt events are identified by a hash of the prompt content
    to enable deduplication of identical prompts at the same time.

    Args:
        session_id: Agent session identifier
        timestamp: When the prompt was submitted
        prompt_hash: Hash of the prompt content (first 16 chars)

    Returns:
        32-character hex string
    """
    return generate_event_id(
        session_id,
        "user_prompt_submitted",
        timestamp,
        prompt_hash[:16],
    )


def generate_stop_event_id(
    session_id: str,
    timestamp: datetime,
    event_type: str = "agent_stopped",
) -> str:
    """Generate deterministic ID for stop events.

    Args:
        session_id: Agent session identifier
        timestamp: When the stop occurred
        event_type: Type of stop event (agent_stopped or subagent_stopped)

    Returns:
        32-character hex string
    """
    return generate_event_id(session_id, event_type, timestamp)


def generate_notification_event_id(
    session_id: str,
    timestamp: datetime,
    content_hash: str,
) -> str:
    """Generate deterministic ID for notification events.

    Args:
        session_id: Agent session identifier
        timestamp: When the notification was sent
        content_hash: Hash of the notification content

    Returns:
        32-character hex string
    """
    return generate_event_id(
        session_id,
        "notification_sent",
        timestamp,
        content_hash[:16],
    )


def generate_git_event_id(
    session_id: str,
    event_type: str,
    timestamp: datetime,
    commit_hash: str | None = None,
    branch: str | None = None,
) -> str:
    """Generate deterministic ID for git events.

    Args:
        session_id: Agent session identifier
        event_type: Type of git event (git_commit, git_branch_created, etc.)
        timestamp: When the git operation occurred
        commit_hash: Git commit hash (for commit events)
        branch: Branch name (for branch events)

    Returns:
        32-character hex string
    """
    content_parts = []
    if commit_hash:
        content_parts.append(commit_hash[:16])
    if branch:
        content_parts.append(branch)

    content_hash = None
    if content_parts:
        content = "|".join(content_parts)
        content_hash = hashlib.sha256(content.encode()).hexdigest()[:16]

    return generate_event_id(session_id, event_type, timestamp, content_hash)
