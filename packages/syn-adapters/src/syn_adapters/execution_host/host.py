"""ExecutionHost: claim, drain, renew and reconcile until drained (ADR-072 D3-D5, #1310 1.5).

Each loop turn:

1. heartbeat, which also reads whether the host is draining (D4, D10);
2. ``sweep_opening``, resolving starts stranded between their two writes (D2);
3. reconciliation of every expired claim this host can fence (D5 A);
4. unless draining, claim until the host's own budget row is full, and drain
   each claimed run in a tracked task whose Lease is renewed every TTL/3;
5. sleep for the loop interval.

A run whose Lease is lost is cancelled, so it takes the shutdown interruption
path (#1381) and its later appends meet the reconciler's at the stream version
(D5 B). A finished run's row is closed under its token, so a stale owner's
close is refused rather than releasing a slot twice.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import timedelta
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

from syn_adapters.execution_host.lease import LeaseKeeper
from syn_adapters.execution_host.reconciler import Reconciler
from syn_domain.contexts.orchestration.ports import RunLeaseLost

if TYPE_CHECKING:
    from syn_adapters.execution_host.ports import ClaimedRunDrainer, DeadHostReaper, RunInterrupter
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
        reaper: DeadHostReaper,
        interrupter: RunInterrupter,
        streams: ExecutionStreamProbe,
        timing: HostTiming | None = None,
    ) -> None:
        self._queue = queue
        self._host = host
        self._capacity = capacity
        self._drainer = drainer
        self._streams = streams
        self._timing = timing or HostTiming()
        self._reconciler = Reconciler(queue, host.host_id, reaper, interrupter)
        self._runs: dict[str, asyncio.Task[None]] = {}
        self._draining = False

    def drain(self) -> None:
        """Stop claiming; ``run_until_drained`` returns once the runs it holds have ended."""
        self._draining = True

    async def run_until_drained(self) -> None:
        """Register, loop until draining with no run held, then deregister.

        Cancelling it is a shutdown: every held run is cancelled, takes the
        interruption path and is awaited; its row is left for its Lease to
        expire and a live executor to reconcile, never re-run (D5 C). The host
        leaves either way, so a restart never inherits its ``draining`` flag.
        """
        await self._queue.register(self._host, self._capacity)
        try:
            while not (await self._turn() and not self._runs):
                await asyncio.sleep(self._timing.loop_interval.total_seconds())
        except asyncio.CancelledError:
            runs = list(self._runs.values())
            for run in runs:
                run.cancel()
            await asyncio.gather(*runs, return_exceptions=True)
            raise
        finally:
            await self._leave()

    async def _leave(self) -> None:
        try:
            await asyncio.shield(self._queue.deregister(self._host.host_id))
        except Exception:
            logger.exception("ExecutionHost %s could not deregister", self._host.host_id)

    async def _turn(self) -> bool:
        """One loop turn; returns whether the host is draining."""
        draining = self._draining
        try:
            draining = await self._queue.heartbeat(self._host.host_id) or draining
            await self._queue.sweep_opening(self._timing.opening_older_than, self._streams)
            await self._reconciler.turn()
            while not draining and (claimed := await self._queue.claim(self._host.host_id)):
                self._spawn(claimed)
        except Exception:
            # The store is the only thing a turn talks to. While it is down no
            # claim is made and no lease renews, so held runs self-fence on
            # their own; the loop's job is to be here when it comes back.
            logger.exception("ExecutionHost %s: loop turn failed", self._host.host_id)
        return draining

    def _spawn(self, claimed: ClaimedRun) -> None:
        task = asyncio.create_task(self._drive(claimed), name=f"run:{claimed.execution_id}")
        self._runs[claimed.execution_id] = task
        task.add_done_callback(lambda _: self._runs.pop(claimed.execution_id, None))

    async def _drive(self, claimed: ClaimedRun) -> None:
        lease = LeaseKeeper(self._queue, claimed, self._timing.renew_every)
        drain: asyncio.Task[object] = asyncio.create_task(self._drainer.run_claimed(claimed))
        keeper = asyncio.create_task(lease.hold(drain))
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
        try:
            await self._queue.close(claimed)
        except RunLeaseLost:
            logger.warning("Close of %s refused: this host no longer owns it", claimed.execution_id)
