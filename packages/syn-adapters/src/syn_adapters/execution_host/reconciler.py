"""Move every expired claim through ``fencing -> reaped -> interrupted`` (ADR-072 D5 A).

An expired Lease is never claimed to run again. Any live executor fences it,
reaps the dead host's containers for that execution, interrupts the run through
its aggregate and releases the slot. A step that cannot be shown complete is
retried on the next turn from where it stopped, never skipped.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from syn_domain.contexts.orchestration.ports import RunLeaseLost

if TYPE_CHECKING:
    from syn_adapters.execution_host.ports import DeadHostReaper, RunInterrupter
    from syn_domain.contexts.orchestration.ports import ExecutionRunQueue, FencedRun

logger = logging.getLogger(__name__)


class Reconciler:
    """One host's share of reconciliation, driven entirely by the queue's rows.

    Holds nothing between turns. Every turn re-reads the ``fencing``/``reaped``
    rows this host owns (adopting any whose reconciler has left), so a write that
    failed before commit, an acknowledgment lost after commit, or a reconciler
    that died part-way are all resumed from what the row says, never from memory.
    """

    def __init__(
        self,
        queue: ExecutionRunQueue,
        host_id: str,
        reaper: DeadHostReaper,
        interrupter: RunInterrupter,
    ) -> None:
        self._queue = queue
        self._host_id = host_id
        self._reaper = reaper
        self._interrupter = interrupter

    async def turn(self) -> None:
        for run in await self._queue.fence_expired(self._host_id):
            logger.warning(
                "Fenced %s: executor %s let its lease expire", run.execution_id, run.executor_id
            )
        for run in await self._queue.reconciling(self._host_id):
            try:
                await self._advance(run)
            except RunLeaseLost:
                logger.warning("Reconciliation of %s moved on without this host", run.execution_id)
            except Exception:
                logger.exception(
                    "Reconciling %s failed; its row says where to resume", run.execution_id
                )

    async def _advance(self, run: FencedRun) -> None:
        if not run.reaped:
            if not await self._reaper.reap(run):
                logger.warning(
                    "Reap of %s on dead executor %s not shown complete; staying fencing",
                    run.execution_id,
                    run.executor_id,
                )
                return
            await self._queue.mark_reaped(run)
        # Interrupting is a no-op on a non-RUNNING aggregate, so a retry after a
        # lost acknowledgment never appends a second terminal event.
        await self._interrupter.interrupt(run)
        await self._queue.close_interrupted(run)
