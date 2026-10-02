"""Adapter-owned bounded background tasks for independent replication operations."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

logger = logging.getLogger(__name__)


class InventoryReplicationWorkPort(Protocol):
    async def enqueue_step(self) -> bool: ...
    async def drain_step(self) -> object: ...


class _ReplicationLane:
    """Own one worker and its independently scheduled enqueue and drain tasks."""

    def __init__(self, work: InventoryReplicationWorkPort, name: str) -> None:
        self._work = work
        self._name = name
        self._enqueue: asyncio.Task[None] | None = None
        self._drain: asyncio.Task[None] | None = None

    def schedule(self) -> None:
        self._enqueue = self._schedule(self._enqueue, self._enqueue_once, f"{self._name}-enqueue")
        self._drain = self._schedule(self._drain, self._drain_once, f"{self._name}-drain")

    @staticmethod
    def _schedule(
        current: asyncio.Task[None] | None,
        action: Callable[[], Coroutine[object, object, None]],
        name: str,
    ) -> asyncio.Task[None]:
        if current is None or current.done():
            return asyncio.create_task(action(), name=name)
        return current

    async def _enqueue_once(self) -> None:
        try:
            await self._work.enqueue_step()
        except Exception:
            logger.warning("Session replication enqueue unavailable; durable work will retry")

    async def _drain_once(self) -> None:
        try:
            await self._work.drain_step()
        except Exception:
            logger.warning("Session replication unavailable; exporter retains pending work")

    def cancel(self) -> tuple[asyncio.Task[None], ...]:
        tasks = tuple(task for task in (self._enqueue, self._drain) if task is not None)
        for task in tasks:
            task.cancel()
        return tasks


class ReplicationSupervisor:
    def __init__(
        self,
        work: InventoryReplicationWorkPort,
        *,
        capture_work: InventoryReplicationWorkPort | None = None,
    ) -> None:
        lanes = [_ReplicationLane(work, "inventory-replication")]
        if capture_work is not None:
            lanes.append(_ReplicationLane(capture_work, "capture-delivery"))
        self._lanes = tuple(lanes)
        self._stopping = False

    async def process_pending(self) -> int:
        if not self._stopping:
            for lane in self._lanes:
                lane.schedule()
        # Remote latency cannot block local projections or publication.
        return 0

    async def stop(self) -> None:
        self._stopping = True
        tasks = tuple(task for lane in self._lanes for task in lane.cancel())
        await asyncio.gather(*tasks, return_exceptions=True)
