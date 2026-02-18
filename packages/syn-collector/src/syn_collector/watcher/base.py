"""Base class for file watchers.

Provides abstract interface for watching files and
extracting events. Concrete implementations handle
different file formats (hook JSONL, transcript JSONL).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator  # noqa: TC003 - used at runtime
from pathlib import Path  # noqa: TC003 - used at runtime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from syn_collector.events.types import CollectedEvent


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
