"""Watcher for Claude transcript JSONL files.

Monitors ~/.claude/projects/**/*.jsonl for token usage
data from Claude's assistant messages.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator  # noqa: TC003 - used at runtime
from datetime import UTC, datetime
from pathlib import Path  # noqa: TC003 - used at runtime
from typing import Any

from syn_collector.events.ids import generate_token_event_id
from syn_collector.events.types import CollectedEvent, EventType
from syn_collector.watcher.base import BaseWatcher

logger = logging.getLogger(__name__)


class TranscriptWatcher(BaseWatcher):
    """Watch Claude transcript files for token usage.

    Monitors transcript JSONL files written by Claude Code and
    extracts token usage data from assistant messages.

    Transcript format:
    {
        "uuid": "...",
        "type": "assistant",
        "message": {
            "usage": {
                "input_tokens": 2500,
                "output_tokens": 135,
                "cache_creation_input_tokens": 3936,
                "cache_read_input_tokens": 14161
            }
        },
        "timestamp": "2025-12-09T10:30:05Z",
        "sessionId": "abc-123"
    }
    """

    def __init__(
        self,
        path: Path,
        *,
        poll_interval: float = 1.0,
        session_id_override: str | None = None,
    ) -> None:
        """Initialize the transcript watcher.

        Args:
            path: Path to transcript JSONL file or directory
            poll_interval: Seconds between file checks
            session_id_override: Override session_id if not in messages
        """
        super().__init__(path, poll_interval=poll_interval)
        self._session_id_override = session_id_override
        self._file_positions: dict[Path, int] = {}
        self._file_inodes: dict[Path, int] = {}

    async def watch(self, *, from_end: bool = True) -> AsyncIterator[CollectedEvent]:
        """Watch for new token usage events.

        If path is a directory, watches all .jsonl files within it.

        Args:
            from_end: Start from end of files (skip existing)

        Yields:
            CollectedEvent for each assistant message with usage data
        """
        while True:
            try:
                files = self._get_transcript_files()

                for file_path in files:
                    # Initialize position for new files
                    if file_path not in self._file_positions:
                        if from_end and file_path.exists():
                            self._file_positions[file_path] = file_path.stat().st_size
                            self._file_inodes[file_path] = file_path.stat().st_ino
                        else:
                            self._file_positions[file_path] = 0

                    async for event in self._read_file(file_path):
                        yield event

                await asyncio.sleep(self._poll_interval)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(
                    f"Error watching transcripts: {e}",
                    extra={"path": str(self.path), "error": str(e)},
                )
                await asyncio.sleep(self._poll_interval)

    async def read_existing(self) -> list[CollectedEvent]:
        """Read all existing events from transcript files.

        Returns:
            List of all token usage events
        """
        events: list[CollectedEvent] = []

        files = self._get_transcript_files()
        for file_path in files:
            # Reset position for this file
            self._file_positions[file_path] = 0

            async for event in self._read_file(file_path):
                events.append(event)

        return events

    def _get_transcript_files(self) -> list[Path]:
        """Get list of transcript files to watch.

        Returns:
            List of .jsonl file paths
        """
        if self.path.is_file():
            return [self.path]

        if self.path.is_dir():
            # Find all .jsonl files recursively
            return list(self.path.rglob("*.jsonl"))

        # Path doesn't exist yet
        return []

    async def _read_file(self, file_path: Path) -> AsyncIterator[CollectedEvent]:
        """Read token events from a transcript file.

        Args:
            file_path: Path to transcript JSONL file

        Yields:
            CollectedEvent for each assistant message with usage
        """
        if not file_path.exists():
            return

        # Check for file rotation
        current_inode = file_path.stat().st_ino
        if file_path in self._file_inodes:
            if current_inode != self._file_inodes[file_path]:
                logger.info(
                    "Transcript file rotated, resetting position",
                    extra={"path": str(file_path)},
                )
                self._file_positions[file_path] = 0
                self._file_inodes[file_path] = current_inode
        else:
            self._file_inodes[file_path] = current_inode

        position = self._file_positions.get(file_path, 0)

        with file_path.open("r", encoding="utf-8") as f:
            f.seek(position)

            buffer = ""
            for line in f:
                buffer += line

                if not buffer.endswith("\n"):
                    continue

                line_content = buffer.strip()
                buffer = ""

                if not line_content:
                    continue

                try:
                    data = json.loads(line_content)
                    event = self._parse_transcript_message(data, file_path)
                    if event:
                        yield event
                except json.JSONDecodeError as e:
                    logger.warning(
                        f"Invalid JSON in transcript: {e}",
                        extra={"file": str(file_path), "error": str(e)},
                    )
                except Exception as e:
                    logger.warning(
                        f"Failed to parse transcript message: {e}",
                        extra={"file": str(file_path), "error": str(e)},
                    )

            self._file_positions[file_path] = f.tell()

    def _parse_transcript_message(
        self,
        data: dict[str, Any],
        file_path: Path,
    ) -> CollectedEvent | None:
        """Parse a transcript message for token usage.

        Only processes 'assistant' type messages with usage data.

        Args:
            data: Raw JSON data from transcript
            file_path: Source file for context

        Returns:
            CollectedEvent or None if no usage data
        """
        # Only process assistant messages
        msg_type = data.get("type")
        if msg_type != "assistant":
            return None

        # Get message content
        message = data.get("message", {})
        usage = message.get("usage")

        if not usage:
            return None

        # Get message UUID
        message_uuid = data.get("uuid", "")
        if not message_uuid:
            logger.debug("Assistant message missing UUID")
            return None

        # Get session ID
        session_id = data.get("sessionId") or self._session_id_override
        if not session_id:
            # Try to extract from file path
            session_id = self._extract_session_from_path(file_path)

        if not session_id:
            logger.warning("Transcript message missing sessionId")
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
        event_id = generate_token_event_id(session_id, timestamp, message_uuid)

        # Build event data with token counts
        event_data = {
            "message_uuid": message_uuid,
            "input_tokens": usage.get("input_tokens", 0),
            "output_tokens": usage.get("output_tokens", 0),
            "cache_creation_input_tokens": usage.get("cache_creation_input_tokens", 0),
            "cache_read_input_tokens": usage.get("cache_read_input_tokens", 0),
        }

        return CollectedEvent(
            event_id=event_id,
            event_type=EventType.TOKEN_USAGE,
            session_id=session_id,
            timestamp=timestamp,
            data=event_data,
        )

    def _extract_session_from_path(self, file_path: Path) -> str | None:
        """Try to extract session ID from file path.

        Claude transcripts are often at:
        ~/.claude/projects/<project-hash>/<session-id>.jsonl

        Args:
            file_path: Path to transcript file

        Returns:
            Session ID or None
        """
        # The filename (without extension) might be the session ID
        stem = file_path.stem
        if stem and len(stem) > 8:  # Reasonable session ID length
            return stem
        return None
