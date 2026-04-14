"""Trigger debouncer.

Debounces rapid-fire webhook events to prevent multiple triggers
for the same logical action (e.g., multiple review comments).
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

logger = logging.getLogger(__name__)


class TriggerDebouncer:
    """Debounce rapid-fire webhook events.

    When multiple events arrive for the same (trigger, PR) combination
    within the debounce window, only the last one fires.
    """

    def __init__(self) -> None:
        """Initialize the debouncer."""
        # ACKNOWLEDGED: triggers deferred on restart, acceptable for debounce use case
        self._pending: dict[str, asyncio.Task] = {}

    async def debounce(
        self,
        key: str,
        delay_seconds: float,
        callback: Callable[[], Coroutine[Any, Any, Any]],
    ) -> None:
        """Schedule callback after delay. Resets if called again with same key.

        Args:
            key: Unique key for this debounce group (e.g. "tr-abc123:pr-42").
            delay_seconds: Seconds to wait before firing.
            callback: Async function to call when debounce timer expires.
        """
        # Cancel existing timer
        if key in self._pending:
            self._pending[key].cancel()
            logger.debug(f"Debounce timer reset for {key}")

        # Schedule new timer
        async def _fire() -> None:
            try:
                await asyncio.sleep(delay_seconds)
                # Only remove our own entry; a newer debounce may have replaced it
                if self._pending.get(key) is task:
                    del self._pending[key]
                await callback()
                logger.info(f"Debounce timer fired for {key}")
            except asyncio.CancelledError:
                pass

        task = asyncio.create_task(_fire())
        task.add_done_callback(self._handle_task_exception)
        self._pending[key] = task

    @staticmethod
    def _handle_task_exception(task: asyncio.Task[None]) -> None:
        """Log exceptions from fire-and-forget debounce tasks."""
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            logger.error(
                "Debounce task failed: %s",
                exc,
                exc_info=(type(exc), exc, exc.__traceback__),
            )

    @property
    def pending_count(self) -> int:
        """Number of pending debounce timers."""
        return len(self._pending)

    def cancel_all(self) -> None:
        """Cancel all pending debounce timers."""
        for task in self._pending.values():
            task.cancel()
        self._pending.clear()


# Singleton
_debouncer: TriggerDebouncer | None = None


def get_debouncer() -> TriggerDebouncer:
    """Get the global debouncer instance."""
    global _debouncer
    if _debouncer is None:
        _debouncer = TriggerDebouncer()
    return _debouncer


def reset_debouncer() -> None:
    """Reset the global debouncer (for testing)."""
    global _debouncer
    if _debouncer:
        _debouncer.cancel_all()
    _debouncer = None
