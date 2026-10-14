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
    """One host's share of reconciliation; owns the runs it fenced until they close.

    The runs it is part-way through are held in memory: they are this process's
    work in progress, not domain state. If this host dies too, those rows stay
    ``fencing``/``reaped`` and hold their slot (FIXME(#1310): 1.5 has no port to
    re-adopt another reconciler's rows; tracked on the plan).
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
        self._to_reap: dict[str, FencedRun] = {}
        self._to_interrupt: dict[str, FencedRun] = {}

    async def turn(self) -> None:
        for run in await self._queue.fence_expired(self._host_id):
            logger.warning(
                "Fenced %s: executor %s let its lease expire", run.execution_id, run.executor_id
            )
            self._to_reap[run.execution_id] = run
        for run in list(self._to_reap.values()):
            await self._reap(run)
        for run in list(self._to_interrupt.values()):
            await self._interrupt(run)

    async def _reap(self, run: FencedRun) -> None:
        try:
            reaped = await self._reaper.reap(run)
        except Exception:
            logger.exception("Reaping fenced run %s failed; staying fencing", run.execution_id)
            return
        if not reaped:
            logger.warning(
                "Reap of %s on dead executor %s not shown complete; staying fencing",
                run.execution_id,
                run.executor_id,
            )
            return
        del self._to_reap[run.execution_id]
        try:
            await self._queue.mark_reaped(run)
        except RunLeaseLost:
            logger.warning("Reconciliation of %s was taken over", run.execution_id)
            return
        self._to_interrupt[run.execution_id] = run

    async def _interrupt(self, run: FencedRun) -> None:
        try:
            await self._interrupter.interrupt(run)
        except Exception:
            logger.exception("Interrupting fenced run %s failed; retrying", run.execution_id)
            return
        del self._to_interrupt[run.execution_id]
        try:
            await self._queue.close_interrupted(run)
        except RunLeaseLost:
            logger.warning("Fenced run %s was closed by another writer", run.execution_id)
