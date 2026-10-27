"""Gated body retention on its own task, so a slow archive never delays reconciliation.

With the confirmed-expiry gate on (#2107), each automatic expiry waits for the
archive through the exporter. ``InventoryWork.schedule`` must not wait with it:
the lane starts one bounded drain in the background and returns at once. At
most one drain is in flight per process. Work is durable SQL, so a drain that
is cancelled or fails resumes on the next tick.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .body_retention import LocalBodyRetention

logger = logging.getLogger(__name__)


class RetentionLane:
    def __init__(self, retention: LocalBodyRetention) -> None:
        self._retention = retention
        self._task: asyncio.Task[None] | None = None
        self._stopping = False

    def schedule(self) -> None:
        if self._stopping or (self._task is not None and not self._task.done()):
            return
        self._task = asyncio.create_task(self._drain_once(), name="body-retention")

    async def _drain_once(self) -> None:
        try:
            await self._retention.drain()
        except Exception as exc:
            # Type only: messages can name archive paths or exporter output.
            logger.error(
                "Local body deletion failed (%s); durable request remains pending",
                type(exc).__name__,
            )

    async def stop(self) -> None:
        self._stopping = True
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
