"""ExecutionHost: claim, drain, renew and reconcile until drained (ADR-072 D3-D5, #1310 1.5).

Each loop turn:

1. heartbeat, which also reads whether the host is draining (D4, D10);
2. start the opening sweep if none is running, resolving starts stranded
   between their two writes (D2);
3. unless draining, acquire up to the free reconciliation slots (taking over
   a departed reconciler's rows, then fencing expired ones) and start
   reconciliation tasks without waiting for them, at most
   ``reconcile_concurrency`` at once (D5 A);
4. unless draining, claim until the host's own budget row is full or the turn
   budget is spent, and drain each claimed run in a tracked task whose Lease
   is renewed every TTL/3;
5. sleep for the loop interval.

The turn never awaits a reap or the sweep, and starts no store call once the
turn budget is spent, so the time between two heartbeats is at most the loop
interval plus the turn budget plus one store call (D4): a stale heartbeat means
the loop stopped, not that it was busy. A reap or sweep still running after one
TTL is warned about once.

A run whose Lease is lost is cancelled, so it takes the shutdown interruption
path (#1381) and its later appends meet the reconciler's at the stream version
(D5 B). A finished run's row is closed under its token, so a stale owner's
close is refused rather than releasing a slot twice.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from datetime import timedelta
from typing import TYPE_CHECKING, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from syn_adapters.execution_host.lease import LeaseKeeper
from syn_adapters.execution_host.reconciler import Reconciler
from syn_domain.contexts.orchestration.ports import RunLeaseLost

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from syn_adapters.execution_host.ports import ClaimedRunDrainer, RunInterrupter, RunReaper
    from syn_domain.contexts.orchestration.ports import (
        ClaimedRun,
        ExecutionRunQueue,
        ExecutionStreamProbe,
        ExecutorHost,
    )

logger = logging.getLogger(__name__)


class HostTiming(BaseModel):
    """The loop's clocks. ``lease_ttl`` must be the TTL the queue was built with."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    loop_interval: timedelta = Field(default=timedelta(seconds=5), gt=timedelta(0))
    lease_ttl: timedelta = Field(default=timedelta(seconds=90), gt=timedelta(0))
    opening_older_than: timedelta = Field(default=timedelta(minutes=2), gt=timedelta(0))
    # Provisional, not measured (#1944); one settings group with the queue's
    # TTL and staleness window is the follow-up before the flag is enabled.
    turn_budget: timedelta = Field(default=timedelta(seconds=15), gt=timedelta(0))
    reconcile_concurrency: int = Field(default=4, ge=1)

    @model_validator(mode="after")
    def _a_busy_turn_never_reads_stale(self) -> Self:
        # The staleness window defaults to the TTL; three heartbeats fit in it.
        if self.loop_interval + self.turn_budget > self.lease_ttl / 3:
            raise ValueError(
                f"loop_interval ({self.loop_interval}) + turn_budget ({self.turn_budget}) "
                f"must not exceed lease_ttl/3 ({self.lease_ttl / 3}): a busy turn would "
                "make a live host read stale (ADR-072 D4)"
            )
        return self

    @property
    def renew_every(self) -> float:
        return self.lease_ttl.total_seconds() / 3


class ExecutionHost:
    """One Executor process's claim loop over the Run Queue."""

    def __init__(
        self,
        queue: ExecutionRunQueue,
        host: ExecutorHost,
        *,
        capacity: int,
        drainer: ClaimedRunDrainer,
        reaper: RunReaper,
        interrupter: RunInterrupter,
        streams: ExecutionStreamProbe,
        timing: HostTiming | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._queue = queue
        self._host = host
        self._capacity = capacity
        self._drainer = drainer
        self._reaper = reaper
        self._streams = streams
        self._timing = timing or HostTiming()
        self._sleep = sleep
        self._clock = clock
        self._reconciler = Reconciler(
            queue,
            host.host_id,
            reaper,
            interrupter,
            concurrency=self._timing.reconcile_concurrency,
            lease_ttl=self._timing.lease_ttl.total_seconds(),
            clock=clock,
        )
        self._runs: dict[str, asyncio.Task[None]] = {}
        self._sweep: asyncio.Task[None] | None = None
        self._sweep_started = 0.0
        self._sweep_warned = False
        self._draining = False
        self._joined = False

    async def join(self) -> None:
        """Register this host into its Executor Pool, once.

        Await it before starting ``run_until_drained`` in a background task, so
        a refused registration (``PoolDefinitionConflict``, D13) reaches the
        caller instead of ending a task nobody awaits. Whoever joins also
        calls ``leave``: a task cancelled before its first step never runs the
        loop's own ``finally``.
        """
        if not self._joined:
            await self._queue.register(self._host, self._capacity)
            self._joined = True

    def drain(self) -> None:
        """Stop claiming and acquiring; returns once held runs and started tasks have ended."""
        self._draining = True

    async def run_until_drained(self) -> None:
        """Join if not yet joined, loop until draining with no run held, then deregister.

        Cancelling it is a shutdown: every held run is cancelled, takes the
        interruption path and is awaited; its row is left for its Lease to
        expire and a live executor to reconcile, never re-run (D5 C).
        Reconciliation and sweep tasks are cancelled too; their rows are taken
        over once this host has left. The host leaves either way, so a restart
        never inherits its ``draining`` flag.
        """
        await self.join()
        try:
            while not (await self._turn() and self._idle()):
                await self._sleep(self._timing.loop_interval.total_seconds())
        except asyncio.CancelledError:
            runs = list(self._runs.values())
            if self._sweep is not None:
                runs.append(self._sweep)
            for run in runs:
                run.cancel()
            await asyncio.gather(*runs, self._reconciler.aclose(), return_exceptions=True)
            raise
        finally:
            await self.leave()

    async def leave(self) -> None:
        """Deregister if joined; never raises. A no-op once left or never joined."""
        if not self._joined:
            return
        self._joined = False
        try:
            await asyncio.shield(self._queue.deregister(self._host.host_id))
        except Exception:
            logger.exception("ExecutionHost %s could not deregister", self._host.host_id)

    def _idle(self) -> bool:
        return not self._runs and self._reconciler.idle and self._sweep is None

    async def _turn(self) -> bool:
        """One loop turn; returns whether the host is draining."""
        started = self._clock()
        budget = self._timing.turn_budget.total_seconds()
        draining = self._draining
        try:
            draining = await self._queue.heartbeat(self._host.host_id) or draining
            self._tend_sweep(start=not draining)
            await self._reconciler.turn(acquire=not draining, deadline=started + budget)
            while (
                not draining
                and self._clock() - started < budget
                and (claimed := await self._queue.claim(self._host.host_id))
            ):
                self._spawn(claimed)
        except Exception:
            # The store is the only thing a turn talks to. While it is down no
            # claim is made and no lease renews, so held runs self-fence on
            # their own; the loop's job is to be here when it comes back.
            logger.exception("ExecutionHost %s: loop turn failed", self._host.host_id)
        return draining

    def _tend_sweep(self, *, start: bool) -> None:
        """Collect a finished opening sweep and start the next; at most one runs (D2).

        A pass still running after one TTL is warned about once, and left
        running: a second pass would only probe the same rows again.
        """
        if self._sweep is not None and self._sweep.done():
            if not self._sweep.cancelled() and (error := self._sweep.exception()) is not None:
                logger.error(
                    "ExecutionHost %s: opening sweep failed",
                    self._host.host_id,
                    exc_info=error,
                )
            self._sweep = None
        if self._sweep is None and start:
            self._sweep = asyncio.create_task(self._sweep_opening(), name="sweep-opening")
            self._sweep_started, self._sweep_warned = self._clock(), False
        elif self._sweep is not None and not self._sweep_warned:
            elapsed = self._clock() - self._sweep_started
            if elapsed > self._timing.lease_ttl.total_seconds():
                self._sweep_warned = True
                logger.warning(
                    "ExecutionHost %s: opening sweep has run %ds; a stream probe may be hung",
                    self._host.host_id,
                    elapsed,
                )

    async def _sweep_opening(self) -> None:
        await self._queue.sweep_opening(self._timing.opening_older_than, self._streams)

    def _spawn(self, claimed: ClaimedRun) -> None:
        if claimed.overflowed:
            # Lane 2 telemetry: the run spilled past a full higher-priority pool (D13).
            logger.info(
                "ExecutionHost %s claimed %s by overflow into Executor Pool %s",
                self._host.host_id,
                claimed.execution_id,
                claimed.pool_id,
            )
        task = asyncio.create_task(self._drive(claimed), name=f"run:{claimed.execution_id}")
        self._runs[claimed.execution_id] = task
        task.add_done_callback(lambda _: self._runs.pop(claimed.execution_id, None))

    async def _drive(self, claimed: ClaimedRun) -> None:
        lease = LeaseKeeper(self._queue, claimed, self._timing.renew_every, sleep=self._sleep)
        drain: asyncio.Task[object] = asyncio.create_task(self._drainer.run_claimed(claimed))
        keeper = asyncio.create_task(lease.hold(drain), name=f"lease:{claimed.execution_id}")
        try:
            await drain
        except asyncio.CancelledError:
            if not lease.lost:
                raise
            return
        except Exception:
            # No terminal event can be shown recorded, so the row stays claimed:
            # its Lease expires and a reconciler interrupts it (D5 A).
            logger.exception("Claimed run %s escaped its drain", claimed.execution_id)
            return
        finally:
            keeper.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await keeper
        if not await self._released(claimed):
            # A drain can return normally over resources it could not remove, a
            # failed delete or a create whose response was lost. Closing would
            # free a slot that may still be running, so the lease expires and a
            # same-scope reconciler reaps before it frees (D3, D5).
            logger.warning(
                "Run %s: resources not shown gone; leaving it charged for reconciliation",
                claimed.execution_id,
            )
            return
        try:
            await self._queue.close(claimed)
        except RunLeaseLost:
            logger.warning("Close of %s refused: this host no longer owns it", claimed.execution_id)

    async def _released(self, claimed: ClaimedRun) -> bool:
        """Whether the backend shows the run's resources gone; a raise is not shown gone."""
        try:
            return await self._reaper.reap(self._host.host_id, claimed.execution_id)
        except Exception:
            logger.exception("Reap of %s before close raised", claimed.execution_id)
            return False
