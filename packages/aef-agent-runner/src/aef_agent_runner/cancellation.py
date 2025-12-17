"""Cancellation handling for agent runner.

The orchestrator can request graceful cancellation by writing
a .cancel file to /workspace/.cancel. The runner polls for this
file and stops execution when detected.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)


class CancellationToken:
    """Token for tracking cancellation requests.

    The token polls for a cancellation file and provides a way
    to check if cancellation has been requested.
    """

    def __init__(
        self,
        cancel_path: Path,
        poll_interval: float = 1.0,
    ) -> None:
        """Initialize cancellation token.

        Args:
            cancel_path: Path to the cancellation file
            poll_interval: How often to check for cancellation (seconds)
        """
        self._cancel_path = cancel_path
        self._poll_interval = poll_interval
        self._cancelled = False
        self._poll_task: asyncio.Task[None] | None = None

    @property
    def is_cancelled(self) -> bool:
        """Check if cancellation has been requested."""
        # Check file directly for synchronous usage
        if self._cancel_path.exists():
            self._cancelled = True
        return self._cancelled

    def cancel(self) -> None:
        """Mark as cancelled (for testing or internal use)."""
        self._cancelled = True

    async def start_polling(self) -> None:
        """Start background polling for cancellation file."""
        if self._poll_task is not None:
            return

        self._poll_task = asyncio.create_task(self._poll_loop())

    async def stop_polling(self) -> None:
        """Stop background polling."""
        if self._poll_task is not None:
            self._poll_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._poll_task
            self._poll_task = None

    async def _poll_loop(self) -> None:
        """Poll for cancellation file in background."""
        while not self._cancelled:
            if self._cancel_path.exists():
                logger.info("Cancellation file detected: %s", self._cancel_path)
                self._cancelled = True
                break
            await asyncio.sleep(self._poll_interval)

    async def wait_for_cancellation(self) -> None:
        """Wait until cancellation is requested."""
        while not self.is_cancelled:
            await asyncio.sleep(self._poll_interval)

    def __enter__(self) -> CancellationToken:
        """Context manager entry."""
        return self

    def __exit__(self, *args: object) -> None:
        """Context manager exit."""
        pass

    async def __aenter__(self) -> CancellationToken:
        """Async context manager entry - starts polling."""
        await self.start_polling()
        return self

    async def __aexit__(self, *args: object) -> None:
        """Async context manager exit - stops polling."""
        await self.stop_polling()


class CancellationError(Exception):
    """Raised when agent execution is cancelled."""

    pass


def check_cancellation(token: CancellationToken) -> None:
    """Check if cancelled and raise if so.

    Args:
        token: Cancellation token to check

    Raises:
        CancellationError: If cancellation has been requested
    """
    if token.is_cancelled:
        raise CancellationError("Agent execution cancelled")
