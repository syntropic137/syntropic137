"""Drain the durable bulk-backfill to-do list. Runs only from live processing."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from syn_domain.contexts.agent_sessions.ports.HistoricalEvidenceSourcePort import (
    HistoricalAcquisitionQuotaExceeded,
)

if TYPE_CHECKING:
    from syn_domain.contexts.agent_sessions.ports.HistoryBackfillQueuePort import (
        HistoryBackfillQueuePort,
    )

    from .BackfillSessionInventoryHandler import BackfillSessionInventoryHandler

logger = logging.getLogger(__name__)


class ProcessHistoryBackfillQueueHandler:
    def __init__(
        self,
        queue: HistoryBackfillQueuePort,
        backfill: BackfillSessionInventoryHandler,
        *,
        lease_seconds: int,
        retry_seconds: int,
        max_items_per_tick: int,
        max_attempts: int,
    ) -> None:
        if lease_seconds < 1 or retry_seconds < 0 or max_items_per_tick < 1 or max_attempts < 1:
            raise ValueError("invalid history backfill worker limits")
        self._queue, self._backfill = queue, backfill
        self._lease, self._retry = lease_seconds, retry_seconds
        self._max_items, self._max_attempts = max_items_per_tick, max_attempts

    async def handle(self) -> int:
        processed = 0
        for _ in range(self._max_items):
            lease = await self._queue.claim(lease_seconds=self._lease)
            if lease is None:
                break
            try:
                result = await self._backfill.handle(lease.item.run, lease.item.idempotency_key)
            except HistoricalAcquisitionQuotaExceeded:
                await self._queue.fail(lease, "history_quota_exceeded")
                continue
            except Exception:
                logger.exception(
                    "History backfill step failed; durable item remains retryable",
                    extra={"execution_id": lease.item.run.execution_id},
                )
                if lease.attempts >= self._max_attempts:
                    await self._queue.fail(lease, "history_backfill_failed")
                else:
                    await self._queue.retry(lease, retry_seconds=self._retry)
                continue
            await self._queue.complete(lease, result.job_id)
            processed += 1
        return processed
