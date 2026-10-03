"""Lifecycle-owned passage-of-time publisher. Pending work itself is durable."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import uuid4

from syn_domain.contexts.agent_sessions import InventoryClockAggregate, ObserveInventoryClockCommand

if TYPE_CHECKING:
    from event_sourcing import EventStoreClient

logger = logging.getLogger(__name__)


class InventoryRecoveryClock:
    def __init__(self, event_store: EventStoreClient, *, interval_seconds: int) -> None:
        self._event_store = event_store
        self._interval = interval_seconds
        self._task: asyncio.Task[None] | None = None

    async def announce(self) -> None:
        now = datetime.now(UTC)
        # Each tick is an independent fact, so replicas need no shared counter.
        tick_id = str(uuid4())
        aggregate = InventoryClockAggregate()
        aggregate.observe(ObserveInventoryClockCommand(aggregate_id=tick_id, observed_at=now))
        await self._event_store.append_events(
            stream_name=f"SessionInventoryClock-{tick_id}",
            events=aggregate.get_uncommitted_events(),
            expected_version=0,
        )

    async def start(self) -> None:
        if self._task is not None:
            return
        # Caller starts only after the coordinator's subscription has opened.
        await self.announce()
        self._task = asyncio.create_task(self._run(), name="session-inventory-recovery-clock")

    async def _run(self) -> None:
        while True:
            await asyncio.sleep(self._interval)
            try:
                await self.announce()
            except Exception:
                logger.exception("Inventory recovery signal failed; retrying next interval")

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task
        self._task = None
