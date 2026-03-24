"""Watcher for hook event JSONL files.

Monitors .agentic/analytics/events.jsonl for hook events
from Claude Code hooks (PreToolUse, PostToolUse, etc).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator  # noqa: TC003 - used at runtime
from functools import partial
from pathlib import Path  # noqa: TC003 - used at runtime
from typing import TYPE_CHECKING

from syn_collector.watcher.base import BaseWatcher, detect_rotation, read_jsonl_lines
from syn_collector.watcher.hook_parser import HOOK_EVENT_MAP, parse_hook_event  # noqa: F401
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

    async def watch(self, *, from_end: bool = True) -> AsyncIterator[CollectedEvent]:
        """Watch for new hook events."""
        if from_end and self.path.exists():
            self._position = self.path.stat().st_size
            self._inode = self.path.stat().st_ino

        while True:
            try:
                if not self.path.exists():
                    await asyncio.sleep(self._poll_interval)
                    continue

                rotated, current_inode = detect_rotation(self.path, self._inode)
                if rotated:
                    logger.info(
                        "Hook file rotated, resetting position", extra={"path": str(self.path)}
                    )
                    self._position = 0
                self._inode = current_inode

                for event in self._read_new_events():
                    yield event

                await asyncio.sleep(self._poll_interval)

            except asyncio.CancelledError:
                break
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
