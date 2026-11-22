"""A run's Lease outlives a teardown slower than its TTL (#2345).

exec-6ea31aa48a83 finished its phase, spent 73 s destroying the workspace, let
its 90 s Lease lapse, and a reconciler closed the succeeded run as interrupted.
Here the teardown the host does after the drain, the reap before the close,
takes several TTLs, against the real in-memory Run Queue: the host's own
reconciler, running every loop turn, is what fences a lapsed Lease.

Time is virtual. The queue's clock, the host's monotonic clock, the host's loop
sleep, the LeaseKeeper's renewal sleep and the slow reap all read one
``_VirtualTime``, which advances only to the next sleeper's deadline once every
task has gone idle. Nothing sleeps on the wall clock, so a slow CI runner
cannot expire a Lease the code renewed (a 60 ms wall-clock TTL did, Codex
review). The production timing is used: 90 s TTL, renewal every 30 s.
"""

from __future__ import annotations

import asyncio
import heapq
import itertools
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from syn_adapters.execution_host import ExecutionHost, HostTiming
from syn_adapters.execution_host.lease import LeaseKeeper
from syn_adapters.execution_runs.memory import InMemoryExecutionRunQueue
from syn_domain.contexts.orchestration.ports import (
    ClaimedRun,
    ExecutorHost,
    FencedRun,
    RunLeaseLost,
    StreamPresence,
)

if TYPE_CHECKING:
    from collections.abc import Callable

pytestmark = pytest.mark.unit

_HOST = ExecutorHost(
    reap_scope="daemon-1", host_id="h-teardown", container_id="c", generation="g", epoch=1
)
_TIMING = HostTiming()  # production defaults: 5 s loop, 90 s TTL, renewal every 30 s
_TEARDOWN = 4 * _TIMING.lease_ttl.total_seconds()
#: Event-loop passes that let every runnable task reach its next await. The
#: queue and fakes do no I/O, so a handful suffices; this is generous.
_SETTLE = 50


class _VirtualTime:
    """One clock for queue, host, keeper and reap; it moves only when all are idle."""

    def __init__(self) -> None:
        self.mono = 0.0
        self._origin = datetime(2026, 11, 22, tzinfo=UTC)
        self._sleepers: list[tuple[float, int, asyncio.Future[None]]] = []
        self._seq = itertools.count()

    def now(self) -> datetime:
        return self._origin + timedelta(seconds=self.mono)

    def monotonic(self) -> float:
        return self.mono

    async def sleep(self, seconds: float) -> None:
        wake: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        heapq.heappush(self._sleepers, (self.mono + seconds, next(self._seq), wake))
        await wake

    async def run_until(self, done: Callable[[], bool], *, limit: float) -> None:
        """Advance to each next deadline, settling the loop in between, until ``done``."""
        while True:
            for _ in range(_SETTLE):
                await asyncio.sleep(0)
            if done():
                return
            while self._sleepers and self._sleepers[0][2].done():
                heapq.heappop(self._sleepers)  # a cancelled sleeper
            if not self._sleepers:
                raise AssertionError("nothing left to wake, and the condition never held")
            deadline, _, wake = heapq.heappop(self._sleepers)
            self.mono = max(self.mono, deadline)
            if self.mono > limit:
                raise AssertionError(f"still waiting at virtual t={self.mono:.0f}s")
            wake.set_result(None)


class _Drainer:
    async def run_claimed(self, claimed: ClaimedRun) -> object:
        return None


class _SlowTeardown:
    """A reap that shows the run's resources gone only after several Lease TTLs."""

    def __init__(self, time: _VirtualTime) -> None:
        self._time = time
        self.reaped: list[str] = []

    async def reap(self, executor_id: str, execution_id: str) -> bool:
        await self._time.sleep(_TEARDOWN)
        self.reaped.append(execution_id)
        return True


class _Interrupter:
    def __init__(self) -> None:
        self.interrupted: list[str] = []

    async def interrupt(self, run: FencedRun) -> None:
        self.interrupted.append(run.execution_id)


class _Streams:
    async def presence(self, execution_id: str) -> StreamPresence:
        return StreamPresence.UNKNOWN


async def test_a_teardown_longer_than_the_lease_ttl_is_neither_fenced_nor_interrupted() -> None:
    time = _VirtualTime()
    queue = InMemoryExecutionRunQueue(lease_ttl=_TIMING.lease_ttl, clock=time.now)
    assert await queue.reserve("e1", 1, is_resume=False)
    await queue.mark_admitted("e1")
    teardown, interrupter = _SlowTeardown(time), _Interrupter()
    host = ExecutionHost(
        queue,
        _HOST,
        capacity=1,
        drainer=_Drainer(),
        reaper=teardown,
        interrupter=interrupter,
        streams=_Streams(),
        timing=_TIMING,
        sleep=time.sleep,
        clock=time.monotonic,
    )
    loop = asyncio.create_task(host.run_until_drained(), name="execution-host")
    async with asyncio.timeout(30):  # hang guard on the wall clock, never a pacing sleep
        await time.run_until(lambda: bool(teardown.reaped), limit=10 * _TEARDOWN)
        # Several more loop turns, so a reconciler would fence a lapsed Lease now.
        settle_until = time.mono + 2 * _TIMING.lease_ttl.total_seconds()
        await time.run_until(lambda: time.mono >= settle_until, limit=10 * _TEARDOWN)
        host.drain()
        await time.run_until(loop.done, limit=20 * _TEARDOWN)
    await loop

    counts = await queue.in_use()
    assert interrupter.interrupted == []
    assert (counts.fencing, counts.reaped, counts.interrupted) == (0, 0, 0)
    assert counts.done == 1
    assert teardown.reaped == ["e1"]
    assert time.mono >= _TEARDOWN  # the teardown really outlasted the Lease TTL


class _RenewalBehindTheClose:
    """A renewal that reaches the store just after the close released the row."""

    def __init__(self) -> None:
        self.released = asyncio.Event()

    async def renew(self, run: ClaimedRun) -> None:
        await self.released.wait()
        raise RunLeaseLost(f"{run.execution_id} is no longer claimed")

    async def close(self) -> None:
        self.released.set()


async def test_a_renewal_refused_because_the_close_released_the_row_is_not_a_lost_lease() -> None:
    queue = _RenewalBehindTheClose()
    claimed = ClaimedRun(
        execution_id="e1", executor_id=_HOST.host_id, token=1, is_resume=False, pool_id="default"
    )
    lease = LeaseKeeper(queue, claimed, 0)  # type: ignore[arg-type]  # renew is all it calls

    async def work() -> object:
        for _ in range(3):  # let the renewal start before the close
            await asyncio.sleep(0)
        await queue.close()
        return None

    drained = asyncio.create_task(work())
    async with asyncio.timeout(1):  # hang guard
        await asyncio.gather(drained, lease.hold(drained))

    assert not lease.lost
