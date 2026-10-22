"""A live host's heartbeat stays fresh however long reconciliation takes (#1944, ADR-072 D4).

The host runs against the real in-memory Run Queue, so the heartbeat is written
and read by the code the queue contract tests pin. Time is fake: the queue's
clock and the host's monotonic clock both read ``_FakeTime``, the host's loop
sleep parks until the test wakes it, and slow work is either a gate the test
opens or ``spend``, which moves time inside the call that took it. Nothing
here sleeps on the wall clock; ``asyncio.timeout`` is only a hang guard that
turns "the host never finished its turn" into a named failure.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta

import pytest

from syn_adapters.execution_host import ExecutionHost, HostTiming
from syn_adapters.execution_host.reconciler import Reconciler
from syn_adapters.execution_runs.memory import InMemoryExecutionRunQueue
from syn_domain.contexts.orchestration.ports import (
    ClaimedRun,
    ExecutorHost,
    FencedRun,
    OpeningSweep,
    StreamPresence,
)

pytestmark = pytest.mark.unit

_WINDOW = 90.0
_TIMING = HostTiming()  # the production defaults: 5 s loop, 15 s budget, 4 concurrent, 90 s TTL
_LIVE = ExecutorHost(reap_scope="daemon-1", host_id="live", container_id="c-live", generation="g", epoch=1)
_DEAD = ExecutorHost(reap_scope="daemon-1", host_id="dead", container_id="c-dead", generation="g", epoch=1)
_PEER_B = ExecutorHost(reap_scope="daemon-1", host_id="b", container_id="c-b", generation="g", epoch=1)
_PEER_C = ExecutorHost(reap_scope="daemon-1", host_id="c", container_id="c-c", generation="g", epoch=1)


class _FakeTime:
    """One clock for queue and host; the host's loop sleep parks until ``turn`` wakes it."""

    def __init__(self) -> None:
        self.mono = 0.0
        self._origin = datetime(2026, 10, 15, tzinfo=UTC)
        self._parks: asyncio.Queue[tuple[float, asyncio.Future[None]]] = asyncio.Queue()
        self._parked: tuple[float, asyncio.Future[None]] | None = None

    def now(self) -> datetime:
        return self._origin + timedelta(seconds=self.mono)

    def monotonic(self) -> float:
        return self.mono

    def spend(self, seconds: float) -> None:
        self.mono += seconds

    async def sleep(self, seconds: float) -> None:
        task = asyncio.current_task()
        if task is not None and task.get_name().startswith("lease:"):
            # Lease renewal is not under test here; a keeper parks for good.
            await asyncio.Event().wait()
        wake: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        self._parks.put_nowait((seconds, wake))
        await wake

    async def parked(self) -> None:
        """Wait until the host has finished a turn and entered its loop sleep."""
        try:
            async with asyncio.timeout(1):  # hang guard, never a pacing sleep
                self._parked = await self._parks.get()
        except TimeoutError:
            raise AssertionError("the host did not finish a loop turn") from None

    async def turn(self) -> None:
        """Let the parked host sleep its interval, then wait for it to park again."""
        self._wake()
        await self.parked()

    async def last_turn(self, loop: asyncio.Task[None]) -> None:
        """Wake the parked host for a turn after which it should leave its loop."""
        self._wake()
        async with asyncio.timeout(1):  # hang guard
            await asyncio.shield(loop)

    def _wake(self) -> None:
        assert self._parked is not None
        seconds, wake = self._parked
        self._parked = None
        self.spend(seconds)
        wake.set_result(None)


class _GatedReaper:
    """The injected slow stop: a reap returns only once the test opens its gate."""

    def __init__(self) -> None:
        self.gate = asyncio.Event()
        self.complete = True
        self.calls: list[str] = []
        self.in_flight: dict[str, int] = {}
        self.max_in_flight = 0
        self.max_per_row = 0
        self.cancelled: list[str] = []
        self.raises: Exception | None = None

    async def reap(self, executor_id: str, execution_id: str) -> bool:
        row = execution_id
        self.calls.append(row)
        self.in_flight[row] = self.in_flight.get(row, 0) + 1
        self.max_per_row = max(self.max_per_row, self.in_flight[row])
        self.max_in_flight = max(self.max_in_flight, sum(self.in_flight.values()))
        try:
            await self.gate.wait()
        except asyncio.CancelledError:
            self.cancelled.append(row)
            raise
        finally:
            self.in_flight[row] -= 1
        if self.raises is not None:
            raise self.raises
        return self.complete


class _Interrupter:
    async def interrupt(self, run: FencedRun) -> None: ...


class _HeldDrainer:
    """Holds every claimed run, so a claim stays claimed and countable."""

    async def run_claimed(self, claimed: ClaimedRun) -> object:
        await asyncio.Event().wait()
        return None


class _Streams:
    async def presence(self, execution_id: str) -> StreamPresence:
        return StreamPresence.UNKNOWN


class _GatedStreams:
    """A stream probe that answers only once the test opens its gate."""

    def __init__(self) -> None:
        self.gate = asyncio.Event()
        self.probed: list[str] = []

    async def presence(self, execution_id: str) -> StreamPresence:
        self.probed.append(execution_id)
        await self.gate.wait()
        return StreamPresence.ABSENT


class _Queue(InMemoryExecutionRunQueue):
    """The real in-memory queue, with the slow or wedged store calls a test asks for."""

    def __init__(self, time: _FakeTime) -> None:
        super().__init__(
            lease_ttl=_TIMING.lease_ttl, heartbeat_stale=timedelta(seconds=_WINDOW), clock=time.now
        )
        self._time = time
        self.claim_takes = 0.0
        self.reconcile_call_takes = 0.0
        self.claimed_by: list[tuple[str, str]] = []
        self.sweep_for_real = False
        self.claims = 0
        self.heartbeats: list[float] = []
        self.wedge_fencing = False
        self.wedged = asyncio.Event()
        self.sweep_gate: asyncio.Event | None = None
        self.sweep_raises: Exception | None = None
        self.sweeps_in_flight = 0
        self.max_sweeps_in_flight = 0
        self.sweeps_started = 0
        self.acquisitions: list[str] = []

    async def heartbeat(self, host_id: str) -> bool:
        self.heartbeats.append(self._time.mono)
        return await super().heartbeat(host_id)

    async def claim(self, host_id: str) -> ClaimedRun | None:
        self._time.spend(self.claim_takes)
        claimed = await super().claim(host_id)
        self.claims += claimed is not None
        if claimed is not None:
            self.claimed_by.append((host_id, claimed.execution_id))
        return claimed

    async def fence_expired(self, reconciler: str, *, limit: int) -> list[FencedRun]:
        self.acquisitions.append("fence_expired")
        self._time.spend(self.reconcile_call_takes)
        if self.wedge_fencing:
            self.wedged.set()
            await asyncio.Event().wait()  # a store call that never returns
        return await super().fence_expired(reconciler, limit=limit)

    async def take_over(self, reconciler: str, *, limit: int) -> list[FencedRun]:
        self.acquisitions.append("take_over")
        self._time.spend(self.reconcile_call_takes)
        return await super().take_over(reconciler, limit=limit)

    async def reconciling(self, reconciler: str) -> list[FencedRun]:
        self.acquisitions.append("reconciling")
        self._time.spend(self.reconcile_call_takes)
        return await super().reconciling(reconciler)

    async def sweep_opening(self, older_than: timedelta, streams: object) -> OpeningSweep:
        self.sweeps_started += 1
        self.sweeps_in_flight += 1
        self.max_sweeps_in_flight = max(self.max_sweeps_in_flight, self.sweeps_in_flight)
        try:
            if self.sweep_for_real:
                return await super().sweep_opening(older_than, streams)  # type: ignore[arg-type]
            if self.sweep_gate is not None:
                await self.sweep_gate.wait()
            if self.sweep_raises is not None:
                raise self.sweep_raises
            return OpeningSweep()
        finally:
            self.sweeps_in_flight -= 1


async def _admit(queue: _Queue, count: int, prefix: str = "e") -> list[str]:
    ids = [f"{prefix}{n:03d}" for n in range(count)]
    for execution_id in ids:
        assert await queue.reserve(execution_id, 1, is_resume=False)
        await queue.mark_admitted(execution_id)
    return ids


async def _a_dead_peer_holding(queue: _Queue, time: _FakeTime, count: int) -> None:
    """``dead`` claims ``count`` runs and stops; its leases and heartbeat then run out."""
    await queue.register(_DEAD, count)
    await queue.heartbeat(_DEAD.host_id)
    await _admit(queue, count, prefix="dead-")
    for _ in range(count):
        assert await queue.claim(_DEAD.host_id) is not None
    time.spend(_WINDOW + 1)


def _live_host(
    queue: _Queue,
    time: _FakeTime,
    reaper: _GatedReaper,
    capacity: int,
    streams: _Streams | _GatedStreams | None = None,
) -> ExecutionHost:
    return ExecutionHost(
        queue,
        _LIVE,
        capacity=capacity,
        drainer=_HeldDrainer(),
        reaper=reaper,
        interrupter=_Interrupter(),
        streams=streams or _Streams(),
        timing=_TIMING,
        sleep=time.sleep,
        clock=time.monotonic,
    )


async def _start(host: ExecutionHost, time: _FakeTime) -> asyncio.Task[None]:
    loop = asyncio.create_task(host.run_until_drained(), name="execution-host")
    await time.parked()
    return loop


async def _stop(loop: asyncio.Task[None]) -> None:
    loop.cancel()
    with pytest.raises(asyncio.CancelledError):
        await loop


async def test_a_live_host_reconciling_20_blocked_reaps_never_reads_stale() -> None:
    time = _FakeTime()
    queue, reaper = _Queue(time), _GatedReaper()
    await _a_dead_peer_holding(queue, time, 20)
    loop = await _start(_live_host(queue, time, reaper, capacity=4), time)

    for _ in range(40):  # 200 s of fake time, more than twice the staleness window
        assert await queue.others_live("observer"), f"live read stale at {time.mono}s"
        assert reaper.max_in_flight <= _TIMING.reconcile_concurrency
        await time.turn()
    assert sum(reaper.in_flight.values()) == _TIMING.reconcile_concurrency
    assert reaper.max_per_row == 1  # one row is never reaped by two tasks at once (D5)

    reaper.gate.set()
    for _ in range(10):
        await time.turn()
    assert (await queue.in_use()).interrupted == 20
    await _stop(loop)


async def test_a_reconciling_host_still_claims_new_work() -> None:
    time = _FakeTime()
    queue, reaper = _Queue(time), _GatedReaper()
    await _a_dead_peer_holding(queue, time, 8)
    loop = await _start(_live_host(queue, time, reaper, capacity=4), time)
    assert reaper.max_in_flight == _TIMING.reconcile_concurrency

    (new,) = await _admit(queue, 1)
    await time.turn()
    assert (_LIVE.host_id, new) in queue.claimed_by
    await _stop(loop)


async def test_a_turn_of_slow_claims_stays_within_its_budget() -> None:
    time = _FakeTime()
    queue, reaper = _Queue(time), _GatedReaper()
    queue.claim_takes = 3.0
    await _admit(queue, 100)
    loop = await _start(_live_host(queue, time, reaper, capacity=100), time)
    budget = _TIMING.turn_budget.total_seconds()

    for _ in range(30):
        # This turn ran from its heartbeat to the park the harness just saw.
        assert time.mono - queue.heartbeats[-1] <= budget + queue.claim_takes
        assert await queue.others_live("observer")
        if queue.claims == 100:
            break
        await time.turn()
    # Counted at the claim: keepers are parked here, so held Leases later expire.
    assert queue.claims == 100
    assert len(queue.heartbeats) > 1  # spread over several turns, not one
    await _stop(loop)


async def test_a_blocked_opening_sweep_does_not_stop_the_loop(
    caplog: pytest.LogCaptureFixture,
) -> None:
    time = _FakeTime()
    queue, reaper = _Queue(time), _GatedReaper()
    queue.sweep_gate = asyncio.Event()
    loop = await _start(_live_host(queue, time, reaper, capacity=4), time)

    for _ in range(40):
        assert await queue.others_live("observer")
        await time.turn()
    assert (queue.sweeps_started, queue.max_sweeps_in_flight) == (1, 1)

    queue.sweep_raises = RuntimeError("probe broke")
    with caplog.at_level(logging.ERROR):
        queue.sweep_gate.set()
        await time.turn()
        await time.turn()
    assert "opening sweep failed" in caplog.text
    assert queue.sweeps_started >= 2  # a failed pass is followed by the next
    await _stop(loop)


async def test_a_wedged_loop_goes_stale() -> None:
    """The other half: a loop stuck in a store call cannot claim, so it must read dead."""
    time = _FakeTime()
    queue, reaper = _Queue(time), _GatedReaper()
    queue.wedge_fencing = True
    loop = asyncio.create_task(
        _live_host(queue, time, reaper, capacity=4).run_until_drained(), name="execution-host"
    )
    async with asyncio.timeout(1):  # hang guard
        await queue.wedged.wait()
    assert await queue.others_live("observer")

    time.spend(_WINDOW + 1)
    assert not await queue.others_live("observer")
    assert await queue.claim(_LIVE.host_id) is None
    await _stop(loop)


async def test_a_host_that_stopped_turning_reads_stale_after_the_window() -> None:
    time = _FakeTime()
    queue, reaper = _Queue(time), _GatedReaper()
    loop = await _start(_live_host(queue, time, reaper, capacity=4), time)
    time.spend(_WINDOW - 1)
    assert await queue.others_live("observer")
    time.spend(2)
    assert not await queue.others_live("observer")
    await _stop(loop)


async def test_a_draining_host_acquires_nothing() -> None:
    time = _FakeTime()
    queue, reaper = _Queue(time), _GatedReaper()
    await _a_dead_peer_holding(queue, time, 6)
    host = _live_host(queue, time, reaper, capacity=4)
    host.drain()
    async with asyncio.timeout(1):  # returns at its first idle turn, without sleeping
        await host.run_until_drained()
    assert queue.acquisitions == []
    assert reaper.calls == []
    assert (await queue.in_use()).claimed == 6  # still expired, left for a live peer


async def test_draining_finishes_started_reconciliation_and_leaves_the_rest() -> None:
    time = _FakeTime()
    queue, reaper = _Queue(time), _GatedReaper()
    await _a_dead_peer_holding(queue, time, 10)
    host = _live_host(queue, time, reaper, capacity=4)
    loop = await _start(host, time)
    started = list(reaper.calls)
    assert len(started) == _TIMING.reconcile_concurrency

    host.drain()
    await time.turn()
    assert not loop.done()  # still finishing what it started
    reaper.gate.set()
    await time.turn()  # the released attempts finish while the host sleeps
    await time.last_turn(loop)
    assert reaper.calls == started  # no new attempt once draining
    counts = await queue.in_use()
    # Acquisition was bounded by the free slots, so the rest were never fenced:
    # they are still expired claims, left for a live peer.
    assert (counts.interrupted, counts.fencing, counts.claimed) == (4, 0, 6)


async def test_shutdown_cancels_reconciliation_and_sweep_tasks() -> None:
    time = _FakeTime()
    queue, reaper = _Queue(time), _GatedReaper()
    queue.sweep_gate = asyncio.Event()
    await _a_dead_peer_holding(queue, time, 6)
    loop = await _start(_live_host(queue, time, reaper, capacity=4), time)
    await _stop(loop)
    assert sorted(reaper.cancelled) == sorted(reaper.calls)
    assert queue.sweeps_in_flight == 0
    counts = await queue.in_use()
    assert (counts.fencing, counts.claimed) == (4, 2)  # acquired up to the free slots only
    assert not await queue.others_live("observer")  # deregistered
    # The rows it owned are taken over once it has left (D5).
    await queue.register(_PEER_B, 4)
    taken = await queue.take_over(_PEER_B.host_id, limit=10)
    assert sorted(run.execution_id for run in taken) == sorted(reaper.calls)


async def test_a_failed_reconciliation_task_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    time = _FakeTime()
    queue, reaper = _Queue(time), _GatedReaper()
    reaper.raises = RuntimeError("docker is gone")
    reaper.gate.set()
    await _a_dead_peer_holding(queue, time, 1)
    with caplog.at_level(logging.ERROR):
        loop = await _start(_live_host(queue, time, reaper, capacity=4), time)
        await time.turn()
    assert "Reconciling dead-000 failed" in caplog.text
    assert len(reaper.calls) >= 2  # retried on a later turn
    assert (await queue.in_use()).fencing == 1
    await _stop(loop)


async def test_a_reap_running_longer_than_the_ttl_is_warned_once(
    caplog: pytest.LogCaptureFixture,
) -> None:
    time = _FakeTime()
    queue, reaper = _Queue(time), _GatedReaper()
    await _a_dead_peer_holding(queue, time, 1)
    with caplog.at_level(logging.WARNING):
        loop = await _start(_live_host(queue, time, reaper, capacity=4), time)
        for _ in range(40):
            await time.turn()
    hung = [r for r in caplog.records if "its reap may be hung" in r.getMessage()]
    assert len(hung) == 1
    assert "dead-000" in hung[0].getMessage()
    await _stop(loop)


async def _peers(queue: _Queue, reaper: _GatedReaper) -> list[Reconciler]:
    for peer in (_PEER_B, _PEER_C):
        await queue.register(peer, 4)
        await queue.heartbeat(peer.host_id)
    return [
        Reconciler(queue, peer.host_id, reaper, _Interrupter(), concurrency=4)
        for peer in (_PEER_B, _PEER_C)
    ]


async def _owned(queue: _Queue, peers: list[Reconciler]) -> list[set[str]]:
    return [
        {run.execution_id for run in await queue.reconciling(peer.host_id)}
        for peer in (_PEER_B, _PEER_C)
    ]


async def test_expired_claims_are_shared_among_live_reconcilers() -> None:
    time = _FakeTime()
    queue, reaper = _Queue(time), _GatedReaper()
    await _a_dead_peer_holding(queue, time, 10)
    peers = await _peers(queue, reaper)

    for peer in peers:
        await peer.turn(acquire=True)
    b, c = await _owned(queue, peers)
    assert (len(b), len(c)) == (4, 4)
    assert not b & c
    assert (await queue.in_use()).claimed == 2  # waiting for a free slot, not taken
    await asyncio.gather(*(peer.aclose() for peer in peers))


async def test_a_departed_reconcilers_backlog_is_shared() -> None:
    time = _FakeTime()
    queue, reaper = _Queue(time), _GatedReaper()
    await _a_dead_peer_holding(queue, time, 10)
    gone = ExecutorHost(reap_scope="daemon-1", host_id="gone", container_id="c-gone", generation="g", epoch=1)
    await queue.register(gone, 1)
    assert len(await queue.fence_expired(gone.host_id, limit=10)) == 10
    await queue.deregister(gone.host_id)
    peers = await _peers(queue, reaper)

    for peer in peers:
        await peer.turn(acquire=True)
    b, c = await _owned(queue, peers)
    assert (len(b), len(c)) == (4, 4)
    assert not b & c
    await asyncio.gather(*(peer.aclose() for peer in peers))


async def test_a_turn_of_slow_reconciliation_store_calls_stays_within_its_budget() -> None:
    """Each store call returns, but slowly: their sum must not outrun the staleness window."""
    time = _FakeTime()
    queue, reaper = _Queue(time), _GatedReaper()
    queue.reconcile_call_takes = 50.0
    await _a_dead_peer_holding(queue, time, 10)
    loop = await _start(_live_host(queue, time, reaper, capacity=4), time)
    budget = _TIMING.turn_budget.total_seconds()

    for _ in range(10):
        assert time.mono - queue.heartbeats[-1] <= budget + queue.reconcile_call_takes
        assert await queue.others_live("observer"), f"live read stale at {time.mono}s"
        await time.turn()
    await _stop(loop)


async def test_an_opening_sweep_running_past_the_ttl_is_warned_once(
    caplog: pytest.LogCaptureFixture,
) -> None:
    time = _FakeTime()
    queue, reaper = _Queue(time), _GatedReaper()
    queue.sweep_for_real = True
    streams = _GatedStreams()
    assert await queue.reserve("stranded", 1, is_resume=False)  # never admitted: ``opening``
    time.spend(_TIMING.opening_older_than.total_seconds() + 1)
    ttl = _TIMING.lease_ttl.total_seconds()

    with caplog.at_level(logging.WARNING):
        loop = await _start(_live_host(queue, time, reaper, capacity=4, streams=streams), time)
        swept_from = queue.heartbeats[0]
        for _ in range(40):  # 200 s of fake time
            hung = [r for r in caplog.records if "opening sweep has run" in r.getMessage()]
            assert len(hung) == (1 if time.mono - swept_from > ttl else 0), time.mono
            assert await queue.others_live("observer")
            await time.turn()
    assert streams.probed == ["stranded"]  # one pass in flight, never restarted

    streams.gate.set()
    await time.turn()
    await time.turn()
    assert (await queue.in_use()).abandoned == 1
    await _stop(loop)
