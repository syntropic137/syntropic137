"""Move every expired claim through ``fencing -> reaped -> interrupted`` (ADR-072 D5 A).

An expired Lease is never claimed to run again. Any live executor fences it,
reaps the dead host's containers for that execution, interrupts the run through
its aggregate and releases the slot. A step that cannot be shown complete is
retried on a later turn from where it stopped, never skipped.

A turn never waits for a reap (D4): each attempt runs in a task the Reconciler
starts and tracks, at most ``concurrency`` at once, so however many rows a host
owns and however slowly Docker answers, the loop turn that drives it stays short.
A turn acquires (takes over, then fences) no more rows than it has free slots,
so a dead or departed host's rows are shared among live executors (D5).
"""

from __future__ import annotations

import asyncio
import itertools
import logging
import math
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from syn_domain.contexts.orchestration.ports import RunLeaseLost

if TYPE_CHECKING:
    from collections.abc import Callable

    from syn_adapters.execution_host.ports import DeadHostReaper, RunInterrupter
    from syn_domain.contexts.orchestration.ports import ExecutionRunQueue, FencedRun

logger = logging.getLogger(__name__)


@dataclass
class _Attempt:
    """One row's reconciliation task, and when it started on the Reconciler's clock."""

    task: asyncio.Task[None]
    started: float
    warned: bool = field(default=False)


class Reconciler:
    """One host's share of reconciliation, driven entirely by the queue's rows.

    Holds only the tasks it started and when each row was last attempted; what
    a row has reached is always read from the row. Every acquiring turn
    re-reads the ``fencing``/``reaped`` rows this host owns, so a write that failed before commit, an
    acknowledgment lost after commit, or a reconciler that died part-way are
    all resumed from what the row says, never from memory.
    """

    def __init__(
        self,
        queue: ExecutionRunQueue,
        host_id: str,
        reaper: DeadHostReaper,
        interrupter: RunInterrupter,
        *,
        concurrency: int = 4,
        lease_ttl: float = 90.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if concurrency < 1:
            raise ValueError("reconciliation concurrency must be at least 1")
        self._queue = queue
        self._host_id = host_id
        self._reaper = reaper
        self._interrupter = interrupter
        self._concurrency = concurrency
        self._lease_ttl = lease_ttl
        self._clock = clock
        self._attempts: dict[str, _Attempt] = {}
        # A scheduling hint, never state: each owned row's place in line, taken
        # when it is first seen and again each time it is attempted. A restart
        # is a new host_id, so losing it loses nothing the rows do not say.
        self._in_line: dict[str, int] = {}
        self._ticket = itertools.count(1)
        self._tried: set[str] = set()

    @property
    def idle(self) -> bool:
        """True when no reconciliation task is in flight."""
        return not self._attempts

    async def turn(self, *, acquire: bool, deadline: float = math.inf) -> None:
        """Acquire up to the free slots and start attempts without awaiting them.

        ``acquire=False`` (a draining host, D10) reads nothing, fences nothing,
        takes over nothing and starts no new attempt; the tasks it already
        started run to their end. No store call starts once the Reconciler's
        clock has reached ``deadline``: what is left waits for the next turn,
        so a turn of slow store calls overruns its budget by one call at most.
        """
        self._warn_long_running()
        if not acquire or self._clock() >= deadline:
            return
        owned = {run.execution_id: run for run in await self._queue.reconciling(self._host_id)}
        # Busy is what holds a slot: a task in flight, or a row this host owns
        # and has never attempted. A row waiting to retry does not, so rows whose
        # reaps keep failing never stop this host acquiring healthy ones.
        busy = len(self._attempts) + sum(
            1 for execution_id in owned if execution_id not in self._tried
        )
        free = self._concurrency - busy
        if free > 0 and self._clock() < deadline:
            for run in await self._queue.take_over(self._host_id, limit=free):
                owned[run.execution_id] = run
                free -= 1
        if free > 0 and self._clock() < deadline:
            for run in await self._queue.fence_expired(self._host_id, limit=free):
                logger.warning(
                    "Fenced %s: executor %s let its lease expire", run.execution_id, run.executor_id
                )
                owned[run.execution_id] = run
        self._tried &= owned.keys()
        self._in_line = {
            execution_id: self._in_line.get(execution_id) or next(self._ticket)
            for execution_id in sorted(owned)
        }
        # Least recently attempted first, so rows whose reaps keep failing
        # never hold up the rows behind them.
        waiting = sorted(
            (run for run in owned.values() if run.execution_id not in self._attempts),
            key=lambda run: self._in_line[run.execution_id],
        )
        for run in waiting[: self._concurrency - len(self._attempts)]:
            self._start(run)

    async def aclose(self) -> None:
        """Cancel and await every in-flight attempt; for shutdown only.

        The rows stay ``fencing``/``reaped`` and are taken over once this host
        has left (D5).
        """
        tasks = [attempt.task for attempt in self._attempts.values()]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    def _start(self, run: FencedRun) -> None:
        execution_id = run.execution_id
        self._in_line[execution_id] = next(self._ticket)
        self._tried.add(execution_id)
        task = asyncio.create_task(self._advance_logged(run), name=f"reconcile:{execution_id}")
        self._attempts[execution_id] = _Attempt(task=task, started=self._clock())
        task.add_done_callback(lambda _: self._attempts.pop(execution_id, None))

    def _warn_long_running(self) -> None:
        now = self._clock()
        for execution_id, attempt in self._attempts.items():
            elapsed = now - attempt.started
            if not attempt.warned and elapsed > self._lease_ttl:
                attempt.warned = True
                logger.warning(
                    "Reconciling %s has run %ds; its reap may be hung", execution_id, elapsed
                )

    async def _advance_logged(self, run: FencedRun) -> None:
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
