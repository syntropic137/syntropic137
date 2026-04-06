"""Base class for file watchers.

Provides abstract interface for watching files and
extracting events. Concrete implementations handle
different file formats (hook JSONL, transcript JSONL).
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from syn_collector.events.types import CollectedEvent

logger = logging.getLogger(__name__)


@dataclass
class FileState:
    """Per-file read state for multi-file watchers."""

    position: int = 0
    inode: int | None = None


class BaseWatcher(ABC):
    """Abstract base class for file watchers.

    Watchers monitor files for new content and yield CollectedEvent
    instances. They handle:
    - Position tracking for resumable reading
    - File rotation detection (inode changes)
    - Partial line handling

    Attributes:
        path: Path to the file or directory to watch
        _position: Current read position in bytes
        _inode: File inode for rotation detection
    """

    def __init__(
        self,
        path: Path,
        *,
        poll_interval: float = 1.0,
    ) -> None:
        """Initialize the watcher.

        Args:
            path: Path to the file or directory to watch
            poll_interval: Seconds between file checks
        """
        self.path = path
        self._poll_interval = poll_interval
        self._position: int = 0
        self._inode: int | None = None

    @abstractmethod
    def watch(self, *, from_end: bool = True) -> AsyncIterator[CollectedEvent]:
        """Watch for new events.

        Continuously monitors the file and yields new events
        as they are appended.

        Note: Implementations should be async generators (async def with yield).
        The abstract method is not async to allow proper type inference.

        Args:
            from_end: Start from end of file (skip existing events)

        Yields:
            CollectedEvent instances as they appear
        """
        ...

    @abstractmethod
    async def read_existing(self) -> list[CollectedEvent]:
        """Read all existing events from file.

        Reads the entire file from the beginning and returns
        all events found.

        Returns:
            List of all events in the file
        """
        ...

    def get_position(self) -> int:
        """Get current read position.

        Returns:
            Byte position in file
        """
        return self._position

    def reset_position(self) -> None:
        """Reset position to start of file."""
        self._position = 0
        self._inode = None

    def set_position(self, position: int) -> None:
        """Set position to specific byte offset.

        Args:
            position: Byte position to set
        """
        self._position = position


def read_jsonl_lines(path: Path, position: int) -> tuple[list[str], int]:
    """Read complete JSONL lines from *path* starting at *position*.

    Partial (unterminated) lines are silently discarded so callers only
    receive well-formed input.

    Args:
        path: File to read.
        position: Byte offset to seek to before reading.

    Returns:
        Tuple of (complete_lines, new_position).
    """
    lines: list[str] = []
    with path.open("r", encoding="utf-8") as f:
        f.seek(position)
        buffer = ""
        for line in f:
            buffer += line
            if not buffer.endswith("\n"):
                continue
            content = buffer.strip()
            buffer = ""
            if content:
                lines.append(content)
        new_position = f.tell()
    return lines, new_position


def detect_rotation(path: Path, stored_inode: int | None) -> tuple[bool, int]:
    """Compare current inode with a stored value to detect file rotation.

    Args:
        path: File to check.
        stored_inode: Previously recorded inode (or None if first check).

    Returns:
        Tuple of (rotated, current_inode).
    """
    current_inode = path.stat().st_ino
    rotated = stored_inode is not None and current_inode != stored_inode
    return rotated, current_inode
