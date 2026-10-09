"""The request latency recorder never blocks, never grows unbounded, and says what it lost (ADR-075)."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from syn_adapters.request_latency import RequestLatencyRecorder, RequestSample
from syn_adapters.request_latency.schema import TABLE

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Sequence

pytestmark = [pytest.mark.unit, pytest.mark.anyio]

#: Never set: an await on it is a database that never answers.
_NEVER = asyncio.Event


def _sample(n: int = 0) -> RequestSample:
    return RequestSample(
        time=datetime(2026, 10, 8, tzinfo=UTC),
        method="GET",
        route="/evals/{eval_id}",
        status=200,
        duration_ms=float(n),
        request_id=f"r{n}",
    )


class _Conn:
    def __init__(self, pool: _Pool) -> None:
        self._pool = pool

    async def copy_records_to_table(
        self, table: str, *, records: Sequence[tuple[object, ...]], columns: Sequence[str]
    ) -> None:
        if self._pool.fail:
            raise ConnectionError("observability db down")
        if self._pool.copy_hangs:
            await _NEVER().wait()
        if self._pool.copy_delay_s:
            await asyncio.sleep(self._pool.copy_delay_s)
        assert table == TABLE
        assert tuple(columns) == ("time", "method", "route", "status", "duration_ms", "request_id")
        self._pool.batches.append(list(records))


class _Pool:
    """asyncpg as the recorder uses it: acquire, then COPY."""

    def __init__(
        self,
        *,
        fail: bool = False,
        acquire_hangs: bool = False,
        copy_hangs: bool = False,
        copy_delay_s: float = 0.0,
    ) -> None:
        self.fail = fail
        self.acquire_hangs = acquire_hangs
        self.copy_hangs = copy_hangs
        self.copy_delay_s = copy_delay_s
        self.batches: list[list[tuple[object, ...]]] = []

    @asynccontextmanager
    async def acquire(self) -> AsyncIterator[_Conn]:
        if self.acquire_hangs:
            await _NEVER().wait()
        yield _Conn(self)


async def _until(predicate: object, *, within_s: float = 2.0) -> None:
    async with asyncio.timeout(within_s):
        while not predicate():  # type: ignore[operator]  # a zero-arg callable
            await asyncio.sleep(0.005)


async def test_a_sample_offered_before_start_is_counted_dropped() -> None:
    recorder = RequestLatencyRecorder()

    recorder.offer(_sample())

    counters = recorder.counters()
    assert (counters.running, counters.dropped, counters.buffered) == (False, 1, 0)


async def test_a_full_buffer_drops_instead_of_growing() -> None:
    recorder = RequestLatencyRecorder(capacity=3, batch_size=100, flush_interval_s=60)
    pool = _Pool()
    recorder.start(pool)  # type: ignore[arg-type]  # a double with asyncpg's acquire/COPY shape

    for n in range(5):
        recorder.offer(_sample(n))

    assert (recorder.counters().buffered, recorder.counters().dropped) == (3, 2)
    await recorder.stop(timeout_s=1)
    assert [len(b) for b in pool.batches] == [3]
    assert recorder.counters().written == 3


async def test_a_full_batch_is_written_without_waiting_for_the_interval() -> None:
    recorder = RequestLatencyRecorder(batch_size=2, flush_interval_s=60)
    pool = _Pool()
    recorder.start(pool)  # type: ignore[arg-type]  # a double with asyncpg's acquire/COPY shape

    recorder.offer(_sample(1))
    recorder.offer(_sample(2))
    await _until(lambda: pool.batches)

    expected = [
        (s.time, s.method, s.route, s.status, s.duration_ms, s.request_id)
        for s in (_sample(1), _sample(2))
    ]
    assert pool.batches == [expected]
    await recorder.stop(timeout_s=1)


async def test_a_failed_write_loses_its_batch_and_says_so() -> None:
    recorder = RequestLatencyRecorder(batch_size=10, flush_interval_s=60)
    recorder.start(_Pool(fail=True))  # type: ignore[arg-type]  # a double with asyncpg's acquire/COPY shape
    for n in range(4):
        recorder.offer(_sample(n))

    await recorder.stop(timeout_s=1)

    counters = recorder.counters()
    assert (counters.written, counters.write_failures, counters.buffered) == (0, 4, 0)


async def test_stop_returns_by_its_deadline_when_the_pool_never_answers() -> None:
    """BLOCKER: a stalled ``pool.acquire()`` used to hold shutdown forever."""
    recorder = RequestLatencyRecorder(batch_size=10, flush_interval_s=60, io_timeout_s=60)
    recorder.start(_Pool(acquire_hangs=True))  # type: ignore[arg-type]  # a double with asyncpg's acquire/COPY shape
    for n in range(4):
        recorder.offer(_sample(n))

    async with asyncio.timeout(2):  # fails the test instead of hanging it
        await recorder.stop(timeout_s=0.1)

    counters = recorder.counters()
    assert (counters.running, counters.discarded, counters.written) == (False, 4, 0)


async def test_a_stalled_acquire_is_abandoned_at_the_io_deadline_and_counted() -> None:
    recorder = RequestLatencyRecorder(batch_size=3, flush_interval_s=60, io_timeout_s=0.05)
    recorder.start(_Pool(acquire_hangs=True))  # type: ignore[arg-type]  # a double with asyncpg's acquire/COPY shape
    for n in range(3):
        recorder.offer(_sample(n))

    await _until(lambda: recorder.counters().write_failures == 3)

    assert recorder.running  # the drain survives a failed batch
    await recorder.stop(timeout_s=1)


async def test_a_batch_mid_write_at_the_shutdown_deadline_is_counted_discarded() -> None:
    """The in-flight batch used to vanish with every counter still at zero."""
    pool = _Pool(copy_hangs=True)
    recorder = RequestLatencyRecorder(batch_size=5, flush_interval_s=60, io_timeout_s=60)
    recorder.start(pool)  # type: ignore[arg-type]  # a double with asyncpg's acquire/COPY shape
    for n in range(5):
        recorder.offer(_sample(n))
    await _until(lambda: recorder.counters().buffered == 0)  # all five are now mid-write

    await recorder.stop(timeout_s=0.1)

    counters = recorder.counters()
    assert (counters.discarded, counters.written, counters.write_failures) == (5, 0, 0)


async def test_a_slow_write_still_finishes_inside_the_shutdown_deadline() -> None:
    pool = _Pool(copy_delay_s=0.05)
    recorder = RequestLatencyRecorder(batch_size=2, flush_interval_s=60, io_timeout_s=1)
    recorder.start(pool)  # type: ignore[arg-type]  # a double with asyncpg's acquire/COPY shape
    for n in range(5):
        recorder.offer(_sample(n))

    await recorder.stop(timeout_s=2)

    counters = recorder.counters()
    assert (counters.written, counters.discarded) == (5, 0)
