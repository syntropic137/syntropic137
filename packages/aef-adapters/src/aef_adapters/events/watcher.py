"""JSONL file watcher for hook events.

Provides mechanisms for reading hook events from JSONL files:
1. Batch reading: Read all events from a file
2. Tailing: Follow the file for new events
3. Watching: Monitor file for changes (using polling)

The watcher handles:
- File rotation (detect when file is truncated/replaced)
- Partial lines (wait for complete JSON)
- Position tracking (resume from last position)

Example:
    watcher = JSONLWatcher(Path(".agentic/analytics/events.jsonl"))

    # Read all existing events
    events = await watcher.read_all()

    # Follow file for new events
    async for event in watcher.tail():
        process(event)
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator  # noqa: TC003 - used at runtime
from pathlib import Path  # noqa: TC003 - used at runtime

from agentic_hooks import HookEvent

logger = logging.getLogger(__name__)


class JSONLWatcher:
    """Watch a JSONL file for hook events.

    Provides methods for reading hook events from JSONL files,
    either in batch mode or as a continuous tail/watch.

    Attributes:
        path: Path to the JSONL file.
        _position: Current read position in file.
        _inode: File inode for rotation detection.
    """

    def __init__(
        self,
        path: Path,
        *,
        poll_interval: float = 1.0,
    ) -> None:
        """Initialize the watcher.

        Args:
            path: Path to the JSONL file to watch.
            poll_interval: Seconds between file checks in watch mode.
        """
        self.path = path
        self._poll_interval = poll_interval
        self._position: int = 0
        self._inode: int | None = None

    async def read_all(self) -> list[HookEvent]:
        """Read all events from the file.

        Returns:
            List of all hook events in the file.

        Raises:
            FileNotFoundError: If the file doesn't exist.
        """
        events: list[HookEvent] = []

        if not self.path.exists():
            return events

        async for event in self._read_file():
            events.append(event)

        return events

    async def read_from(self, position: int = 0) -> tuple[list[HookEvent], int]:
        """Read events from a specific position.

        Args:
            position: Byte position to start reading from.

        Returns:
            Tuple of (events, new_position).
        """
        events: list[HookEvent] = []

        if not self.path.exists():
            return events, position

        self._position = position

        async for event in self._read_file():
            events.append(event)

        return events, self._position

    async def tail(
        self,
        *,
        from_end: bool = True,
    ) -> AsyncIterator[HookEvent]:
        """Tail the file for new events.

        Continuously yields new events as they are appended to the file.
        Handles file rotation by detecting inode changes.

        Args:
            from_end: Start from end of file (skip existing events).

        Yields:
            New hook events as they appear.
        """
        if from_end and self.path.exists():
            # Seek to end of file
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
                        "File rotated, resetting position",
                        extra={"path": str(self.path)},
                    )
                    self._position = 0
                    self._inode = current_inode

                # Read new content
                async for event in self._read_file():
                    yield event

                await asyncio.sleep(self._poll_interval)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(
                    f"Error reading file: {e}",
                    extra={"path": str(self.path), "error": str(e)},
                )
                await asyncio.sleep(self._poll_interval)

    async def _read_file(self) -> AsyncIterator[HookEvent]:
        """Read events from file starting at current position.

        Updates _position as events are read.

        Yields:
            Hook events parsed from the file.
        """
        if not self.path.exists():
            return

        # Read file content from current position
        # Using sync I/O here as aiofiles adds complexity for tail mode
        with self.path.open("r", encoding="utf-8") as f:
            f.seek(self._position)

            buffer = ""
            for line in f:
                buffer += line

                # Check if we have a complete line
                if not buffer.endswith("\n"):
                    continue

                # Try to parse the line
                line_content = buffer.strip()
                buffer = ""

                if not line_content:
                    continue

                try:
                    data = json.loads(line_content)
                    event = HookEvent.from_dict(data)
                    yield event
                except json.JSONDecodeError as e:
                    logger.warning(
                        f"Invalid JSON line: {e}",
                        extra={"line": line_content[:100], "error": str(e)},
                    )
                except Exception as e:
                    logger.warning(
                        f"Failed to parse event: {e}",
                        extra={"line": line_content[:100], "error": str(e)},
                    )

            # Update position
            self._position = f.tell()

    def get_position(self) -> int:
        """Get current read position.

        Returns:
            Byte position in file.
        """
        return self._position

    def reset_position(self) -> None:
        """Reset position to start of file."""
        self._position = 0
        self._inode = None


class MultiFileWatcher:
    """Watch multiple JSONL files for hook events.

    Useful for monitoring multiple session or workspace event files.

    Example:
        watcher = MultiFileWatcher([
            Path(".agentic/analytics/events.jsonl"),
            Path(".agentic/analytics/session-abc.jsonl"),
        ])

        async for path, event in watcher.watch_all():
            print(f"Event from {path}: {event.event_type}")
    """

    def __init__(
        self,
        paths: list[Path],
        *,
        poll_interval: float = 1.0,
    ) -> None:
        """Initialize the multi-file watcher.

        Args:
            paths: List of JSONL files to watch.
            poll_interval: Seconds between file checks.
        """
        self._watchers = {path: JSONLWatcher(path, poll_interval=poll_interval) for path in paths}

    async def watch_all(
        self,
        *,
        from_end: bool = True,
    ) -> AsyncIterator[tuple[Path, HookEvent]]:
        """Watch all files for new events.

        Yields:
            Tuples of (file_path, hook_event).
        """

        # Create tasks for each watcher
        async def watch_single(
            path: Path,
            watcher: JSONLWatcher,
        ) -> AsyncIterator[tuple[Path, HookEvent]]:
            async for event in watcher.tail(from_end=from_end):
                yield (path, event)

        # Merge all streams
        tasks = [watch_single(path, watcher) for path, watcher in self._watchers.items()]

        # Simple round-robin polling (could be improved with asyncio.gather)
        while True:
            for task in tasks:
                try:
                    # Get next event with timeout
                    event_tuple = await asyncio.wait_for(
                        task.__anext__(),
                        timeout=0.1,
                    )
                    yield event_tuple
                except TimeoutError:
                    continue
                except StopAsyncIteration:
                    continue
                except asyncio.CancelledError:
                    return
