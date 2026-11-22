"""A run's Lease outlives a teardown slower than its TTL (#2345).

exec-6ea31aa48a83 finished its phase, spent 73 s destroying the workspace, let
its 90 s Lease lapse, and a reconciler closed the succeeded run as interrupted.
Here the teardown the host does after the drain, the reap before the close,
takes several TTLs, against the real in-memory Run Queue: the host's own
reconciler, running every loop turn, is what fences a lapsed Lease.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest

from syn_adapters.execution_host import ExecutionHost, HostTiming
from syn_adapters.execution_runs.memory import InMemoryExecutionRunQueue
from syn_domain.contexts.orchestration.ports import (
    ClaimedRun,
    ExecutorHost,
    FencedRun,
    StreamPresence,
)

pytestmark = pytest.mark.unit

_HOST = ExecutorHost(
    reap_scope="daemon-1", host_id="h-teardown", container_id="c", generation="g", epoch=1
)
_TIMING = HostTiming(
    loop_interval=timedelta(milliseconds=5),
    lease_ttl=timedelta(milliseconds=60),
    turn_budget=timedelta(milliseconds=4),
)
_TEARDOWN = 4 * _TIMING.lease_ttl.total_seconds()


class _Drainer:
    async def run_claimed(self, claimed: ClaimedRun) -> object:
        return None


class _SlowTeardown:
    """A reap that shows the run's resources gone only after several Lease TTLs."""

    def __init__(self) -> None:
        self.reaped: list[str] = []

    async def reap(self, executor_id: str, execution_id: str) -> bool:
        await asyncio.sleep(_TEARDOWN)
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
    queue = InMemoryExecutionRunQueue(lease_ttl=_TIMING.lease_ttl)
    assert await queue.reserve("e1", 1, is_resume=False)
    await queue.mark_admitted("e1")
    teardown, interrupter = _SlowTeardown(), _Interrupter()
    host = ExecutionHost(
        queue,
        _HOST,
        capacity=1,
        drainer=_Drainer(),
        reaper=teardown,
        interrupter=interrupter,
        streams=_Streams(),
        timing=_TIMING,
    )
    loop = asyncio.create_task(host.run_until_drained())
    async with asyncio.timeout(10 * _TEARDOWN):  # hang guard
        while not teardown.reaped:
            await asyncio.sleep(0.005)
    host.drain()
    await asyncio.wait_for(loop, 10 * _TEARDOWN)

    counts = await queue.in_use()
    assert interrupter.interrupted == []
    assert (counts.fencing, counts.reaped, counts.interrupted) == (0, 0, 0)
    assert counts.done == 1
    assert teardown.reaped == ["e1"]
