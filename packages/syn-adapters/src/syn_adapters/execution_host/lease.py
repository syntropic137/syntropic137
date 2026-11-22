"""Keep one claimed run's Lease, and fence the run when the Lease is lost (ADR-072 D4, D5 B)."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from syn_domain.contexts.orchestration.ports import RunLeaseLost

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from syn_domain.contexts.orchestration.ports import ClaimedRun, ExecutionRunQueue

logger = logging.getLogger(__name__)


class LeaseKeeper:
    """Renews ``run`` every ``every`` seconds while ``work`` runs, and cancels it on loss.

    ``work`` is everything the host does under the claim, the drain and the
    teardown checks after it up to the close: a Lease that lapses in any of
    it lets a reconciler fence a run whose outcome is already recorded (#2345).

    A failed renewal for any reason other than ``RunLeaseLost`` (the store is
    briefly unreachable) is retried at the next tick: the Lease is either still
    valid then, or it has expired and the renewal says so. Either way no run is
    kept alive on the strength of a write that did not happen.
    """

    def __init__(
        self,
        queue: ExecutionRunQueue,
        run: ClaimedRun,
        every: float,
        *,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._queue = queue
        self._sleep = sleep
        self._run = run
        self._every = every
        self.lost = False

    async def hold(self, work: asyncio.Task[object]) -> None:
        while not work.done():
            await self._sleep(self._every)
            try:
                await self._queue.renew(self._run)
            except RunLeaseLost:
                if work.done():
                    # The renewal raced the close that ended the work: the row
                    # is released, not taken, so there is nothing to fence.
                    return
                self.lost = True
                logger.warning(
                    "Lease on %s lost: self-fencing, the run takes the interruption path",
                    self._run.execution_id,
                )
                work.cancel()
                return
            except Exception:
                logger.exception("Renewing the lease on %s failed", self._run.execution_id)
