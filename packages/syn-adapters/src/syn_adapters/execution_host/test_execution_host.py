"""ExecutionHost's control flow against a scripted queue (#1310 1.5).

These pin what the host DOES with each answer the queue gives: they cannot
show the answers are right. Lease, fencing and event-sequence claims are proven
on real Postgres and the real event store in
``apps/syn-api/tests/integration/test_1310_execution_host_*.py``.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest

from syn_adapters.execution_host import ExecutionHost, HostTiming
from syn_adapters.execution_host.reconciler import Reconciler
from syn_domain.contexts.orchestration.ports import (
    ClaimedRun,
    ExecutorHost,
    FencedRun,
    OpeningSweep,
    RunLeaseLost,
    StreamPresence,
)

pytestmark = pytest.mark.unit

_HOST = ExecutorHost(host_id="h-unit", container_id="c", generation="g", epoch=0)
_FAST = HostTiming(
    loop_interval=timedelta(milliseconds=5),
    lease_ttl=timedelta(milliseconds=30),
    opening_older_than=timedelta(minutes=2),
)


class _Queue:
    """Hands out ``runs`` once each; ``renew_raises`` makes every renewal lose the lease."""

    def __init__(self, runs: list[ClaimedRun], *, renew_raises: bool = False) -> None:
        self.to_claim = list(runs)
        self.renew_raises = renew_raises
        self.closed: list[str] = []
        self.renewed = 0
        self.fenced: list[FencedRun] = []
        self.rows: dict[str, FencedRun] = {}
        """The durable ``fencing``/``reaped`` rows; ``reconciling`` reads only these."""
        self.reaped: list[str] = []
        self.interrupted: list[str] = []
        self.fail: dict[str, str] = {}
        """Write name -> ``before`` (raise, row unchanged) or ``after`` (commit, then raise)."""
        self.deregistered = False

    async def register(self, host: ExecutorHost, capacity: int) -> None: ...
    async def deregister(self, host_id: str) -> None:
        self.deregistered = True

    async def heartbeat(self, host_id: str) -> bool:
        return False

    async def sweep_opening(self, older_than: timedelta, streams: object) -> OpeningSweep:
        return OpeningSweep()

    async def claim(self, host_id: str) -> ClaimedRun | None:
        return self.to_claim.pop(0) if self.to_claim else None

    async def renew(self, run: ClaimedRun) -> None:
        self.renewed += 1
        if self.renew_raises:
            raise RunLeaseLost(run.execution_id)

    async def close(self, run: ClaimedRun) -> None:
        self.closed.append(run.execution_id)

    async def fence_expired(self, reconciler: str) -> list[FencedRun]:
        fenced, self.fenced = self.fenced, []
        self.rows.update({run.execution_id: run for run in fenced})
        return fenced

    async def reconciling(self, reconciler: str) -> list[FencedRun]:
        return list(self.rows.values())

    async def mark_reaped(self, run: FencedRun) -> None:
        self._maybe_fail("mark_reaped", "before")
        self.rows[run.execution_id] = run.model_copy(update={"reaped": True})
        self.reaped.append(run.execution_id)
        self._maybe_fail("mark_reaped", "after")

    async def close_interrupted(self, run: FencedRun) -> None:
        self._maybe_fail("close_interrupted", "before")
        del self.rows[run.execution_id]
        self.interrupted.append(run.execution_id)
        self._maybe_fail("close_interrupted", "after")

    def _maybe_fail(self, write: str, when: str) -> None:
        if self.fail.get(write) == when:
            del self.fail[write]
            raise ConnectionError(f"{write} lost its connection {when} commit")


class _Drainer:
    def __init__(self, *, block: bool = False) -> None:
        self.block = block
        self.cancelled: list[str] = []
        self.drained: list[str] = []

    async def run_claimed(self, claimed: ClaimedRun) -> object:
        try:
            if self.block:
                await asyncio.Event().wait()
            self.drained.append(claimed.execution_id)
        except asyncio.CancelledError:
            self.cancelled.append(claimed.execution_id)
            raise
        return None


class _Reaper:
    def __init__(self, complete: bool) -> None:
        self.complete = complete
        self.calls: list[tuple[str, str]] = []

    async def reap(self, run: FencedRun) -> bool:
        self.calls.append((run.executor_id, run.execution_id))
        return self.complete


class _Interrupter:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def interrupt(self, run: FencedRun) -> None:
        self.calls.append(run.execution_id)


class _Streams:
    async def presence(self, execution_id: str) -> StreamPresence:
        return StreamPresence.UNKNOWN


def _claimed(execution_id: str) -> ClaimedRun:
    return ClaimedRun(
        execution_id=execution_id, executor_id=_HOST.host_id, token=1, is_resume=False
    )


def _host(queue: _Queue, drainer: _Drainer, reaper: _Reaper | None = None) -> ExecutionHost:
    return ExecutionHost(
        queue,  # type: ignore[arg-type]  # scripted double: only what the loop calls
        _HOST,
        capacity=2,
        drainer=drainer,
        reaper=reaper or _Reaper(complete=True),
        interrupter=_Interrupter(),
        streams=_Streams(),
        timing=_FAST,
    )


async def _until(predicate: object, budget: float = 2.0) -> None:
    async with asyncio.timeout(budget):
        while not predicate():  # type: ignore[operator]
            await asyncio.sleep(0.002)


async def test_a_drained_run_is_closed_under_its_claim_and_the_host_deregisters() -> None:
    queue, drainer = _Queue([_claimed("e1"), _claimed("e2")]), _Drainer()
    host = _host(queue, drainer)
    loop = asyncio.create_task(host.run_until_drained())
    await _until(lambda: len(queue.closed) == 2)
    host.drain()
    await asyncio.wait_for(loop, 2)
    assert sorted(drainer.drained) == ["e1", "e2"]
    assert sorted(queue.closed) == ["e1", "e2"]
    assert queue.deregistered


async def test_a_lost_lease_cancels_the_run_and_never_closes_its_row() -> None:
    queue, drainer = _Queue([_claimed("e1")], renew_raises=True), _Drainer(block=True)
    host = _host(queue, drainer)
    loop = asyncio.create_task(host.run_until_drained())
    await _until(lambda: drainer.cancelled == ["e1"])
    host.drain()
    await asyncio.wait_for(loop, 2)
    assert queue.renewed >= 1
    assert queue.closed == []  # the reconciler owns the row now (D5)


async def test_a_held_lease_is_renewed_while_the_run_drains() -> None:
    queue, drainer = _Queue([_claimed("e1")]), _Drainer(block=True)
    host = _host(queue, drainer)
    loop = asyncio.create_task(host.run_until_drained())
    await _until(lambda: queue.renewed >= 3)
    assert drainer.cancelled == []
    loop.cancel()
    with pytest.raises(asyncio.CancelledError):
        await loop
    # Shutdown cancels the run into its interruption path and leaves the row.
    assert drainer.cancelled == ["e1"]
    assert queue.closed == []
    assert queue.deregistered


async def test_a_draining_host_claims_nothing() -> None:
    queue, drainer = _Queue([_claimed("e1")]), _Drainer()
    host = _host(queue, drainer)
    host.drain()
    await asyncio.wait_for(host.run_until_drained(), 2)
    assert drainer.drained == []
    assert queue.to_claim == [_claimed("e1")]


async def test_an_incomplete_reap_keeps_the_run_fencing_until_a_later_turn_completes_it() -> None:
    queue = _Queue([])
    fenced = FencedRun(execution_id="e9", executor_id="dead", reconciler=_HOST.host_id, token=2)
    queue.fenced = [fenced]
    reaper, interrupter = _Reaper(complete=False), _Interrupter()
    reconciler = Reconciler(queue, _HOST.host_id, reaper, interrupter)  # type: ignore[arg-type]
    await reconciler.turn()
    assert (queue.reaped, interrupter.calls, queue.interrupted) == ([], [], [])
    reaper.complete = True
    await reconciler.turn()
    assert reaper.calls == [("dead", "e9"), ("dead", "e9")]
    assert queue.reaped == ["e9"]
    assert interrupter.calls == ["e9"]
    assert queue.interrupted == ["e9"]


@pytest.mark.parametrize("write", ["mark_reaped", "close_interrupted"])
@pytest.mark.parametrize("when", ["before", "after"])
async def test_a_failed_reconciliation_write_is_resumed_from_the_row(write: str, when: str) -> None:
    queue = _Queue([])
    queue.fenced = [
        FencedRun(execution_id="e9", executor_id="dead", reconciler=_HOST.host_id, token=2)
    ]
    queue.fail = {write: when}
    reaper, interrupter = _Reaper(complete=True), _Interrupter()
    reconciler = Reconciler(queue, _HOST.host_id, reaper, interrupter)  # type: ignore[arg-type]
    await reconciler.turn()
    await reconciler.turn()
    assert queue.interrupted == ["e9"]
    assert queue.reaped == ["e9"]
    assert queue.rows == {}
    await reconciler.turn()
    assert queue.interrupted == ["e9"]


async def test_a_fresh_reconciler_finishes_a_row_its_predecessor_left_reaped() -> None:
    queue = _Queue([])
    queue.rows = {
        "e9": FencedRun(
            execution_id="e9", executor_id="dead", reconciler=_HOST.host_id, token=3, reaped=True
        )
    }
    reaper, interrupter = _Reaper(complete=True), _Interrupter()
    await Reconciler(queue, _HOST.host_id, reaper, interrupter).turn()  # type: ignore[arg-type]
    assert reaper.calls == []  # already reaped: the row says so
    assert interrupter.calls == ["e9"]
    assert queue.interrupted == ["e9"]
