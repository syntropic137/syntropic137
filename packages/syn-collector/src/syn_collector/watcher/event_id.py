"""Event ID dispatch for hook events.

Replaces the if/elif chain in HookWatcher._generate_event_id with a
dispatch-dict mapping EventType groups to ID generator functions.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Any

from syn_collector.events.ids import (
    generate_git_event_id,
    generate_notification_event_id,
    generate_session_event_id,
    generate_stop_event_id,
    generate_tool_event_id,
    generate_user_prompt_event_id,
)
from syn_collector.events.types import EventType

if TYPE_CHECKING:
    from datetime import datetime

_TOOL_EVENTS = frozenset(
    {
        EventType.TOOL_EXECUTION_STARTED,
        EventType.TOOL_EXECUTION_COMPLETED,
        EventType.TOOL_BLOCKED,
    }
)

_STOP_EVENTS = frozenset(
    {
        EventType.AGENT_STOPPED,
        EventType.SUBAGENT_STARTED,
        EventType.SUBAGENT_STOPPED,
    }
)

_GIT_EVENTS = frozenset(
    {
        EventType.GIT_COMMIT,
        EventType.GIT_BRANCH_CREATED,
        EventType.GIT_BRANCH_SWITCHED,
        EventType.GIT_MERGE_COMPLETED,
        EventType.GIT_COMMITS_REWRITTEN,
        EventType.GIT_PUSH_STARTED,
        EventType.GIT_PUSH_COMPLETED,
    }
)


def dispatch_event_id(
    event_type: EventType,
    session_id: str,
    timestamp: datetime,
    data: dict[str, Any],
) -> str:
    """Generate a deterministic event ID based on event type.

    Args:
        event_type: Type of event
        session_id: Session identifier
        timestamp: Event timestamp
        data: Event data dict

    Returns:
        32-character event ID
    """
    if event_type in _TOOL_EVENTS:
        return generate_tool_event_id(
            session_id,
            event_type.value,
            timestamp,
            data.get("tool_name", "unknown"),
            data.get("tool_use_id", ""),
        )

    if event_type == EventType.USER_PROMPT_SUBMITTED:
        prompt = str(data.get("prompt", ""))
        prompt_hash = hashlib.sha256(prompt.encode()).hexdigest()
        return generate_user_prompt_event_id(session_id, timestamp, prompt_hash)

    if event_type in _STOP_EVENTS:
        return generate_stop_event_id(session_id, timestamp, event_type.value)

    if event_type == EventType.NOTIFICATION_SENT:
        content = str(data.get("content_preview", data.get("message", "")))
        content_hash = hashlib.sha256(content.encode()).hexdigest()
        return generate_notification_event_id(session_id, timestamp, content_hash)

    if event_type in _GIT_EVENTS:
        return generate_git_event_id(
            session_id,
            event_type.value,
            timestamp,
            data.get("commit_hash"),
            data.get("branch"),
        )

    return generate_session_event_id(session_id, event_type.value, timestamp)
