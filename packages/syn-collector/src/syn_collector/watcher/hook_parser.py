"""Hook event parsing logic.

Extracted from HookWatcher to reduce module complexity.
"""

from __future__ import annotations

import logging
from typing import Any

from syn_collector.events.types import CollectedEvent, EventType
from syn_collector.watcher.event_id import dispatch_event_id
from syn_collector.watcher.parsing import parse_timestamp

logger = logging.getLogger(__name__)

# Mapping from hook event types to our EventType enum
HOOK_EVENT_MAP: dict[str, EventType] = {
    # Session lifecycle events
    "session_started": EventType.SESSION_STARTED,
    "session_ended": EventType.SESSION_ENDED,
    "agent_stopped": EventType.AGENT_STOPPED,
    "subagent_started": EventType.SUBAGENT_STARTED,
    "subagent_stopped": EventType.SUBAGENT_STOPPED,
    # Tool execution events
    "tool_execution_started": EventType.TOOL_EXECUTION_STARTED,
    "tool_execution_completed": EventType.TOOL_EXECUTION_COMPLETED,
    "tool_blocked": EventType.TOOL_BLOCKED,
    # User interaction events
    "user_prompt_submitted": EventType.USER_PROMPT_SUBMITTED,
    "notification_sent": EventType.NOTIFICATION_SENT,
    # Context management
    "pre_compact": EventType.PRE_COMPACT,
    # Git operations
    "git_commit": EventType.GIT_COMMIT,
    "git_branch_created": EventType.GIT_BRANCH_CREATED,
    "git_branch_switched": EventType.GIT_BRANCH_SWITCHED,
    "git_merge_completed": EventType.GIT_MERGE_COMPLETED,
    "git_commits_rewritten": EventType.GIT_COMMITS_REWRITTEN,
    "git_push_started": EventType.GIT_PUSH_STARTED,
    "git_push_completed": EventType.GIT_PUSH_COMPLETED,
    # Hook handler name mappings (alternative names)
    "pre-tool-use": EventType.TOOL_EXECUTION_STARTED,
    "post-tool-use": EventType.TOOL_EXECUTION_COMPLETED,
    "session-start": EventType.SESSION_STARTED,
    "session-end": EventType.SESSION_ENDED,
    "user-prompt": EventType.USER_PROMPT_SUBMITTED,
    "stop": EventType.AGENT_STOPPED,
    "subagent-start": EventType.SUBAGENT_STARTED,
    "subagent-stop": EventType.SUBAGENT_STOPPED,
    "notification": EventType.NOTIFICATION_SENT,
}


def parse_hook_event(
    data: dict[str, Any],
    session_id_override: str | None = None,
) -> CollectedEvent | None:
    """Parse a hook event dict into CollectedEvent.

    Args:
        data: Raw JSON data from hook file.
        session_id_override: Fallback session ID if not in data.

    Returns:
        CollectedEvent or None if invalid.
    """
    raw_event_type = data.get("event_type") or data.get("handler", "")
    event_type = HOOK_EVENT_MAP.get(raw_event_type)

    if event_type is None:
        logger.debug(f"Unknown hook event type: {raw_event_type}")
        return None

    session_id = data.get("session_id") or session_id_override
    if not session_id:
        logger.warning("Hook event missing session_id")
        return None

    timestamp = parse_timestamp(data.get("timestamp"))
    event_id = dispatch_event_id(event_type, session_id, timestamp, data)

    event_data = {
        k: v
        for k, v in data.items()
        if k not in ("event_type", "handler", "session_id", "timestamp")
    }

    return CollectedEvent(
        event_id=event_id,
        event_type=event_type,
        session_id=session_id,
        timestamp=timestamp,
        data=event_data,
    )
