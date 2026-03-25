"""Watcher for Claude transcript JSONL files.

Monitors ~/.claude/projects/**/*.jsonl for token usage
data from Claude's assistant messages.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator  # noqa: TC003 - used at runtime
from functools import partial
from pathlib import Path  # noqa: TC003 - used at runtime
from typing import TYPE_CHECKING

from syn_collector.watcher.base import BaseWatcher, FileState, detect_rotation, read_jsonl_lines
from syn_collector.watcher.parsing import parse_jsonl_events
from syn_collector.watcher.transcript_parser import parse_transcript_message

if TYPE_CHECKING:
    from syn_collector.events.types import CollectedEvent

logger = logging.getLogger(__name__)


class TranscriptWatcher(BaseWatcher):
    """Watch Claude transcript files for token usage."""

    def __init__(
        self,
        path: Path,
        *,
        poll_interval: float = 1.0,
        session_id_override: str | None = None,
    ) -> None:
        super().__init__(path, poll_interval=poll_interval)
        self._session_id_override = session_id_override
        self._file_state: dict[Path, FileState] = {}

    def _process_all_files(self, from_end: bool) -> list[CollectedEvent]:
        """Read new events from all transcript files."""
        events: list[CollectedEvent] = []
        for file_path in self._get_transcript_files():
            self._ensure_file_state(file_path, from_end)
            events.extend(self._read_file(file_path))
        return events

    async def watch(self, *, from_end: bool = True) -> AsyncIterator[CollectedEvent]:
        """Watch for new token usage events."""
        while True:
            try:
                for event in self._process_all_files(from_end):
                    yield event
                await asyncio.sleep(self._poll_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error watching transcripts: {e}", extra={"path": str(self.path)})
                await asyncio.sleep(self._poll_interval)

    async def read_existing(self) -> list[CollectedEvent]:
        """Read all existing events from transcript files."""
        events: list[CollectedEvent] = []
        for file_path in self._get_transcript_files():
            self._file_state[file_path] = FileState(position=0)
            events.extend(self._read_file(file_path))
        return events

    def _ensure_file_state(self, file_path: Path, from_end: bool) -> None:
        """Initialize file state for a newly discovered file."""
        if file_path in self._file_state:
            return
        if from_end and file_path.exists():
            stat = file_path.stat()
            self._file_state[file_path] = FileState(position=stat.st_size, inode=stat.st_ino)
        else:
            self._file_state[file_path] = FileState(position=0)

    def _get_transcript_files(self) -> list[Path]:
        """Get list of transcript files to watch."""
        if self.path.is_file():
            return [self.path]
        if self.path.is_dir():
            return list(self.path.rglob("*.jsonl"))
        return []

    def _read_file(self, file_path: Path) -> list[CollectedEvent]:
        """Read token events from a transcript file."""
        if not file_path.exists():
            return []

        state = self._file_state.get(file_path, FileState())

        rotated, current_inode = detect_rotation(file_path, state.inode)
        if rotated:
            logger.info(
                "Transcript file rotated, resetting position", extra={"path": str(file_path)}
            )
            state.position = 0
        state.inode = current_inode

        lines, new_position = read_jsonl_lines(file_path, state.position)
        state.position = new_position
        self._file_state[file_path] = state

        parser = partial(
            parse_transcript_message,
            file_path=file_path,
            session_id_override=self._session_id_override,
        )
        return parse_jsonl_events(lines, parser, source_label="transcript")
