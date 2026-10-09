"""A bounded, batched, non-blocking writer of request samples (ADR-073).

``offer`` is called on the request path, so it does no I/O and never waits: it
appends to a bounded buffer, or counts a drop when the buffer is full or the
recorder is not running. A background task drains the buffer into
``api_request_latency`` with one ``COPY`` per batch. A failed write drops that
batch and counts it; telemetry is never retried at the expense of requests.

Lane 2: nothing here touches the event store or an aggregate.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections import deque
from dataclasses import dataclass
from typing import TYPE_CHECKING

from syn_adapters.request_latency.schema import TABLE

if TYPE_CHECKING:
    from datetime import datetime

    import asyncpg

logger = logging.getLogger(__name__)

_COLUMNS = ("time", "method", "route", "status", "duration_ms", "request_id")


@dataclass(frozen=True, slots=True)
class RequestSample:
    """One answered request. Never a path, query, header or body (ADR-073)."""

    time: datetime
    method: str
    route: str
    """The route TEMPLATE (``/evals/{eval_id}``), or ``<unmatched>``."""
    status: int
    duration_ms: float
    """Arrival to response start."""
    request_id: str


@dataclass(frozen=True, slots=True)
class RecorderCounters:
    """What the recorder did with the samples it was offered, since the process started."""

    running: bool
    written: int
    dropped: int
    """Offered while the buffer was full or the recorder was not running."""
    write_failures: int
    """Samples lost because their batch could not be written."""
    buffered: int


class RequestLatencyRecorder:
    """Buffers request samples in memory and writes them in batches."""

    def __init__(
        self,
        *,
        capacity: int = 10_000,
        batch_size: int = 500,
        flush_interval_s: float = 1.0,
    ) -> None:
        self._capacity = capacity
        self._batch_size = batch_size
        self._flush_interval_s = flush_interval_s
        self._buffer: deque[RequestSample] = deque()
        self._pool: asyncpg.Pool | None = None
        self._task: asyncio.Task[None] | None = None
        self._wake = asyncio.Event()
        self._written = 0
        self._dropped = 0
        self._write_failures = 0

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def offer(self, sample: RequestSample) -> None:
        """Keep the sample for the next batch, or count it dropped. Never blocks."""
        if self._task is None or len(self._buffer) >= self._capacity:
            self._dropped += 1
            return
        self._buffer.append(sample)
        if len(self._buffer) >= self._batch_size:
            self._wake.set()

    def counters(self) -> RecorderCounters:
        return RecorderCounters(
            running=self.running,
            written=self._written,
            dropped=self._dropped,
            write_failures=self._write_failures,
            buffered=len(self._buffer),
        )

    def start(self, pool: asyncpg.Pool) -> None:
        """Begin draining into ``pool``. Idempotent."""
        if self.running:
            return
        self._pool = pool
        self._wake = asyncio.Event()
        self._task = asyncio.create_task(self._run(), name="request-latency-recorder")

    async def stop(self) -> None:
        """Stop the drain task and write what is buffered, once."""
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        await self.flush()
        self._pool = None

    async def flush(self) -> None:
        """Write everything buffered now, a batch at a time."""
        while self._buffer and self._pool is not None:
            batch = [
                self._buffer.popleft() for _ in range(min(self._batch_size, len(self._buffer)))
            ]
            await self._write(self._pool, batch)

    async def _run(self) -> None:
        while True:
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._wake.wait(), timeout=self._flush_interval_s)
            self._wake.clear()
            await self.flush()

    async def _write(self, pool: asyncpg.Pool, batch: list[RequestSample]) -> None:
        records = [
            (s.time, s.method, s.route, s.status, s.duration_ms, s.request_id) for s in batch
        ]
        try:
            async with pool.acquire() as conn:
                await conn.copy_records_to_table(TABLE, records=records, columns=_COLUMNS)  # type: ignore[union-attr]  # asyncpg generates PoolConnectionProxy's methods at runtime
        except Exception:
            self._write_failures += len(batch)
            logger.warning("request latency batch of %d not written", len(batch), exc_info=True)
            return
        self._written += len(batch)


# One per API process, like the middleware stack that feeds it.
request_latency_recorder = RequestLatencyRecorder()
