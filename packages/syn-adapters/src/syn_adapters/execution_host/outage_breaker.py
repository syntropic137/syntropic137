"""The Outage Breaker: disable an executor's claims after consecutive failed creates (#1917).

Research decision 2. When a backend's creates keep failing (an E2B outage, a
bad template), an executor that kept claiming would fail every run it took. The
breaker counts consecutive failures on the executor's own budget row and, at
the threshold, disables its claims for a cooldown. Capacity is never touched,
so the D3 ``CHECK`` holds while runs are charged, and charged runs finish or are
fenced normally. Executors in other pools never wait on it: a disabled executor
advertises no room, so it holds nothing back (D13).

The count lives on the row, not in this object, so it survives the process and
every replica of one executor agrees on it.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from syn_domain.contexts.orchestration.ports import ExecutionRunQueue

logger = logging.getLogger(__name__)


class OutageBreaker:
    """Reports one executor's workspace-create outcomes to its budget row."""

    def __init__(
        self,
        queue: Callable[[], Awaitable[ExecutionRunQueue | None]],
        host_id: str,
        *,
        threshold: int,
        cooldown: timedelta,
    ) -> None:
        if threshold < 1 or cooldown <= timedelta(0):
            raise ValueError("breaker threshold and cooldown must be positive")
        self._queue = queue
        self._host_id = host_id
        self._threshold = threshold
        self._cooldown = cooldown

    async def failed(self) -> None:
        """One create failed. Never raises: the create's own error is what the caller needs."""
        try:
            queue = await self._queue()
            if queue is None:
                return
            if await queue.record_create_failure(
                self._host_id, threshold=self._threshold, cooldown=self._cooldown
            ):
                logger.error(
                    "Executor %s: workspace creates failing; claims disabled for %ds "
                    "(Outage Breaker, %d consecutive)",
                    self._host_id,
                    self._cooldown.total_seconds(),
                    self._threshold,
                )
        except Exception:
            logger.exception("Executor %s: could not record a failed create", self._host_id)

    async def succeeded(self) -> None:
        """One create succeeded: the count restarts. Never raises."""
        try:
            queue = await self._queue()
            if queue is not None:
                await queue.record_create_success(self._host_id)
        except Exception:
            logger.exception("Executor %s: could not record a successful create", self._host_id)
