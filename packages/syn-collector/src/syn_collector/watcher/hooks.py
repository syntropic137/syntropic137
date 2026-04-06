"""Watcher for hook event JSONL files.

Monitors .agentic/analytics/events.jsonl for hook events
from Claude Code hooks (PreToolUse, PostToolUse, etc).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING

from syn_collector.watcher.base import BaseWatcher, detect_rotation, read_jsonl_lines
from syn_collector.watcher.hook_parser import HOOK_EVENT_MAP, parse_hook_event
from syn_collector.watcher.parsing import parse_jsonl_events

if TYPE_CHECKING:
    from syn_collector.events.types import CollectedEvent

logger = logging.getLogger(__name__)


class HookWatcher(BaseWatcher):
    """Watch hook event JSONL files for new events."""

    def __init__(
        self,
        path: Path,
        *,
        poll_interval: float = 1.0,
        session_id_override: str | None = None,
    ) -> None:
        super().__init__(path, poll_interval=poll_interval)
        self._session_id_override = session_id_override

    def _init_end_position(self) -> None:
        """Seek to end of file so only new events are emitted."""
        if self.path.exists():
            stat = self.path.stat()
            self._position = stat.st_size
            self._inode = stat.st_ino

    def _check_rotation_and_read(self) -> list[CollectedEvent]:
        """Handle file rotation then read new events from current position."""
        rotated, current_inode = detect_rotation(self.path, self._inode)
        if rotated:
            logger.info("Hook file rotated, resetting position", extra={"path": str(self.path)})
            self._position = 0
        self._inode = current_inode
        return self._read_new_events()

    def _poll_once(self) -> list[CollectedEvent]:
        """Run a single poll cycle: check file existence, rotation, and read."""
        if not self.path.exists():
            return []
        return self._check_rotation_and_read()

    async def watch(self, *, from_end: bool = True) -> AsyncIterator[CollectedEvent]:
        """Watch for new hook events.

        CancelledError (BaseException) propagates naturally to stop the generator.
        """
        if from_end:
            self._init_end_position()

        while True:
            try:
                for event in self._poll_once():
                    yield event
            except Exception as e:
                logger.error(f"Error reading hook file: {e}", extra={"path": str(self.path)})
            await asyncio.sleep(self._poll_interval)

    async def read_existing(self) -> list[CollectedEvent]:
        """Read all existing events from file."""
        if not self.path.exists():
            return []
        original_position = self._position
        self._position = 0
        events = self._read_new_events()
        if original_position > 0:
            self._position = original_position
        return events

    def _read_new_events(self) -> list[CollectedEvent]:
        """Read events from current position."""
        if not self.path.exists():
            return []
        lines, new_position = read_jsonl_lines(self.path, self._position)
        self._position = new_position
        parser = partial(parse_hook_event, session_id_override=self._session_id_override)
        return parse_jsonl_events(lines, parser, source_label="hook file")
