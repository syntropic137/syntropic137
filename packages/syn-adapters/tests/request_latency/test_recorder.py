"""The request latency recorder never blocks, never grows unbounded, and says what it lost (ADR-073)."""

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
        assert table == TABLE
        assert tuple(columns) == ("time", "method", "route", "status", "duration_ms", "request_id")
        self._pool.batches.append(list(records))


class _Pool:
    """asyncpg as the recorder uses it: acquire, then COPY."""

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.batches: list[list[tuple[object, ...]]] = []

    @asynccontextmanager
    async def acquire(self) -> AsyncIterator[_Conn]:
        yield _Conn(self)


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
    await recorder.stop()
    assert [len(b) for b in pool.batches] == [3]
    assert recorder.counters().written == 3


async def test_a_full_batch_is_written_without_waiting_for_the_interval() -> None:
    recorder = RequestLatencyRecorder(batch_size=2, flush_interval_s=60)
    pool = _Pool()
    recorder.start(pool)  # type: ignore[arg-type]  # a double with asyncpg's acquire/COPY shape

    recorder.offer(_sample(1))
    recorder.offer(_sample(2))
    for _ in range(20):
        await asyncio.sleep(0)
        if pool.batches:
            break

    assert pool.batches == [
        [
            (s.time, s.method, s.route, s.status, s.duration_ms, s.request_id)
            for s in (_sample(1), _sample(2))
        ]
    ]
    await recorder.stop()


async def test_a_failed_write_loses_its_batch_and_says_so() -> None:
    recorder = RequestLatencyRecorder(batch_size=10, flush_interval_s=60)
    recorder.start(_Pool(fail=True))  # type: ignore[arg-type]  # a double with asyncpg's acquire/COPY shape
    for n in range(4):
        recorder.offer(_sample(n))

    await recorder.stop()

    counters = recorder.counters()
    assert (counters.written, counters.write_failures, counters.buffered) == (0, 4, 0)
