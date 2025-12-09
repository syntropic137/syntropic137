"""Watcher for hook event JSONL files.

Monitors .agentic/analytics/events.jsonl for hook events
from Claude Code hooks (PreToolUse, PostToolUse, etc).
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator  # noqa: TC003 - used at runtime
from datetime import UTC, datetime
from pathlib import Path  # noqa: TC003 - used at runtime
from typing import Any

from aef_collector.events.ids import (
    generate_git_event_id,
    generate_notification_event_id,
    generate_session_event_id,
    generate_stop_event_id,
    generate_tool_event_id,
    generate_user_prompt_event_id,
)
from aef_collector.events.types import CollectedEvent, EventType
from aef_collector.watcher.base import BaseWatcher

logger = logging.getLogger(__name__)


# Mapping from hook event types to our EventType enum
HOOK_EVENT_MAP: dict[str, EventType] = {
    # Session lifecycle events
    "session_started": EventType.SESSION_STARTED,
    "session_ended": EventType.SESSION_ENDED,
    "agent_stopped": EventType.AGENT_STOPPED,
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
    "subagent-stop": EventType.SUBAGENT_STOPPED,
    "notification": EventType.NOTIFICATION_SENT,
}


class HookWatcher(BaseWatcher):
    """Watch hook event JSONL files for new events.

    Monitors the hook events file written by Claude Code hooks
    and yields CollectedEvent instances for each new entry.

    The watcher handles:
    - File rotation (inode change detection)
    - Partial lines (waits for complete JSON)
    - Position tracking for resume
    """

    def __init__(
        self,
        path: Path,
        *,
        poll_interval: float = 1.0,
        session_id_override: str | None = None,
    ) -> None:
        """Initialize the hook watcher.

        Args:
            path: Path to the hook events JSONL file
            poll_interval: Seconds between file checks
            session_id_override: Override session_id if not in events
        """
        super().__init__(path, poll_interval=poll_interval)
        self._session_id_override = session_id_override

    async def watch(self, *, from_end: bool = True) -> AsyncIterator[CollectedEvent]:
        """Watch for new hook events.

        Args:
            from_end: Start from end of file (skip existing)

        Yields:
            CollectedEvent for each new hook event
        """
        if from_end and self.path.exists():
            self._position = self.path.stat().st_size
            self._inode = self.path.stat().st_ino

        while True:
            try:
                if not self.path.exists():
                    await asyncio.sleep(self._poll_interval)
                    continue

                # Check for file rotation
                current_inode = self.path.stat().st_ino
                if self._inode is not None and current_inode != self._inode:
                    logger.info(
                        "Hook file rotated, resetting position",
                        extra={"path": str(self.path)},
                    )
                    self._position = 0
                    self._inode = current_inode

                # Read new content
                async for event in self._read_new_events():
                    yield event

                await asyncio.sleep(self._poll_interval)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(
                    f"Error reading hook file: {e}",
                    extra={"path": str(self.path), "error": str(e)},
                )
                await asyncio.sleep(self._poll_interval)

    async def read_existing(self) -> list[CollectedEvent]:
        """Read all existing events from file.

        Returns:
            List of all hook events
        """
        events: list[CollectedEvent] = []

        if not self.path.exists():
            return events

        # Reset position to read from start
        original_position = self._position
        self._position = 0

        async for event in self._read_new_events():
            events.append(event)

        # Restore position if needed
        if original_position > 0:
            self._position = original_position

        return events

    async def _read_new_events(self) -> AsyncIterator[CollectedEvent]:
        """Read events from current position.

        Yields:
            CollectedEvent for each valid line
        """
        if not self.path.exists():
            return

        with self.path.open("r", encoding="utf-8") as f:
            f.seek(self._position)

            buffer = ""
            for line in f:
                buffer += line

                # Wait for complete line
                if not buffer.endswith("\n"):
                    continue

                line_content = buffer.strip()
                buffer = ""

                if not line_content:
                    continue

                try:
                    data = json.loads(line_content)
                    event = self._parse_hook_event(data)
                    if event:
                        yield event
                except json.JSONDecodeError as e:
                    logger.warning(
                        f"Invalid JSON in hook file: {e}",
                        extra={"line": line_content[:100], "error": str(e)},
                    )
                except Exception as e:
                    logger.warning(
                        f"Failed to parse hook event: {e}",
                        extra={"line": line_content[:100], "error": str(e)},
                    )

            self._position = f.tell()

    def _parse_hook_event(self, data: dict[str, Any]) -> CollectedEvent | None:
        """Parse a hook event dict into CollectedEvent.

        Args:
            data: Raw JSON data from hook file

        Returns:
            CollectedEvent or None if invalid
        """
        # Get event type
        raw_event_type = data.get("event_type") or data.get("handler", "")
        event_type = HOOK_EVENT_MAP.get(raw_event_type)

        if event_type is None:
            logger.debug(f"Unknown hook event type: {raw_event_type}")
            return None

        # Get session ID
        session_id = data.get("session_id") or self._session_id_override
        if not session_id:
            logger.warning("Hook event missing session_id")
            return None

        # Parse timestamp
        timestamp_str = data.get("timestamp")
        if timestamp_str:
            try:
                timestamp = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
            except ValueError:
                timestamp = datetime.now(UTC)
        else:
            timestamp = datetime.now(UTC)

        # Generate deterministic event ID
        event_id = self._generate_event_id(event_type, session_id, timestamp, data)

        # Build event data (exclude meta fields)
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

    def _generate_event_id(
        self,
        event_type: EventType,
        session_id: str,
        timestamp: datetime,
        data: dict[str, Any],
    ) -> str:
        """Generate deterministic event ID based on event type.

        Args:
            event_type: Type of event
            session_id: Session identifier
            timestamp: Event timestamp
            data: Event data dict

        Returns:
            32-character event ID
        """
        import hashlib

        # Tool execution events
        if event_type in (
            EventType.TOOL_EXECUTION_STARTED,
            EventType.TOOL_EXECUTION_COMPLETED,
            EventType.TOOL_BLOCKED,
        ):
            tool_name = data.get("tool_name", "unknown")
            tool_use_id = data.get("tool_use_id", "")
            return generate_tool_event_id(
                session_id, event_type.value, timestamp, tool_name, tool_use_id
            )

        # User prompt events
        elif event_type == EventType.USER_PROMPT_SUBMITTED:
            prompt = str(data.get("prompt", ""))
            prompt_hash = hashlib.sha256(prompt.encode()).hexdigest()
            return generate_user_prompt_event_id(session_id, timestamp, prompt_hash)

        # Stop events (agent/subagent)
        elif event_type in (EventType.AGENT_STOPPED, EventType.SUBAGENT_STOPPED):
            return generate_stop_event_id(session_id, timestamp, event_type.value)

        # Notification events
        elif event_type == EventType.NOTIFICATION_SENT:
            content = str(data.get("content_preview", data.get("message", "")))
            content_hash = hashlib.sha256(content.encode()).hexdigest()
            return generate_notification_event_id(session_id, timestamp, content_hash)

        # Git events
        elif event_type in (
            EventType.GIT_COMMIT,
            EventType.GIT_BRANCH_CREATED,
            EventType.GIT_BRANCH_SWITCHED,
            EventType.GIT_MERGE_COMPLETED,
            EventType.GIT_COMMITS_REWRITTEN,
            EventType.GIT_PUSH_STARTED,
            EventType.GIT_PUSH_COMPLETED,
        ):
            commit_hash = data.get("commit_hash")
            branch = data.get("branch")
            return generate_git_event_id(
                session_id, event_type.value, timestamp, commit_hash, branch
            )

        # Default: session-style events
        else:
            return generate_session_event_id(session_id, event_type.value, timestamp)
