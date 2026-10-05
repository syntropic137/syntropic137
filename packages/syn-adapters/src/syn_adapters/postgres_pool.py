"""asyncpg pools that can say how busy they are (#1583).

A dashboard stall could not be attributed: was the API waiting on Postgres, or
was the request never reaching the API? This module answers the Postgres half
in two ways, both Lane 2 (observability) and both lost on restart:

* ``pool_stats()`` - a point-in-time gauge per live pool: size, how many
  connections are checked out, and how many callers are waiting for one.
* ``tally_pool_wait()`` - how long the current task (and the tasks it spawns)
  spent waiting in ``acquire()``, summed over every pool.

asyncpg exposes size and idle count publicly but not its queue of waiters, so
waiting is counted here, around ``acquire()``, rather than read from the pool.
That is why every pool in the process must be made by ``create_pool`` below: a
pool made by ``asyncpg.create_pool`` works but is invisible to both.
"""

from __future__ import annotations

import time
import weakref
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import asyncpg
from asyncpg.pool import Pool

if TYPE_CHECKING:
    from collections.abc import Generator, Iterator
    from types import TracebackType


@dataclass(frozen=True)
class PoolStats:
    """One pool at one instant."""

    name: str
    size: int
    max_size: int
    in_use: int
    waiting: int


class PoolWaitTally:
    """Milliseconds spent waiting for pool connections within one scope."""

    def __init__(self) -> None:
        self.wait_ms = 0.0


_current_tally: ContextVar[PoolWaitTally | None] = ContextVar("pool_wait_tally", default=None)
_live_pools: weakref.WeakSet[_InstrumentedPool] = weakref.WeakSet()


@contextmanager
def tally_pool_wait() -> Iterator[PoolWaitTally]:
    """Sum acquire() waits, across every pool, made inside this block."""
    tally = PoolWaitTally()
    token = _current_tally.set(tally)
    try:
        yield tally
    finally:
        _current_tally.reset(token)


def pool_stats() -> list[PoolStats]:
    """Gauges for every open pool made by ``create_pool``, ordered by name."""
    return sorted(
        (pool.stats() for pool in list(_live_pools) if not pool.is_closing()),
        key=lambda s: s.name,
    )


class _TimedAcquire:
    """``pool.acquire()``'s context, with the wait counted and timed.

    Supports both spellings asyncpg does: ``async with pool.acquire()`` and
    ``await pool.acquire()``.
    """

    def __init__(self, pool: _InstrumentedPool, timeout: float | None) -> None:
        self._pool = pool
        self._inner = Pool.acquire(pool, timeout=timeout)

    async def _waited(self, acquiring: Any) -> asyncpg.Connection:  # noqa: ANN401 - asyncpg's acquire awaitables are untyped
        self._pool.waiting += 1
        start = time.perf_counter()
        try:
            return await acquiring
        finally:
            self._pool.waiting -= 1
            tally = _current_tally.get()
            if tally is not None:
                tally.wait_ms += (time.perf_counter() - start) * 1000

    async def __aenter__(self) -> asyncpg.Connection:
        return await self._waited(self._inner.__aenter__())

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self._inner.__aexit__(exc_type, exc, tb)

    def __await__(self) -> Generator[Any, None, asyncpg.Connection]:
        return self._waited(self._inner).__await__()


class _InstrumentedPool(Pool):
    """An asyncpg ``Pool`` whose ``acquire()`` is counted and timed."""

    def __init__(self, *args: Any, name: str, **kwargs: Any) -> None:  # noqa: ANN401 - forwarded verbatim to asyncpg.Pool
        super().__init__(*args, **kwargs)
        self.name = name
        self.waiting = 0

    def acquire(self, *, timeout: float | None = None) -> _TimedAcquire:  # type: ignore[override]  # same protocol as PoolAcquireContext: async with / await
        return _TimedAcquire(self, timeout)

    def stats(self) -> PoolStats:
        size = self.get_size()
        return PoolStats(
            name=self.name,
            size=size,
            max_size=self.get_max_size(),
            in_use=size - self.get_idle_size(),
            waiting=self.waiting,
        )


async def create_pool(dsn: str, *, name: str, min_size: int, max_size: int) -> asyncpg.Pool:
    """``asyncpg.create_pool``, but visible to ``pool_stats`` and ``tally_pool_wait``.

    *name* is what /health reports the pool as; say what the pool serves.
    """
    # asyncpg.create_pool is only ``Pool(...)`` with these defaults filled in;
    # it takes no pool class, so the defaults are restated here.
    pool = _InstrumentedPool(
        dsn,
        name=name,
        min_size=min_size,
        max_size=max_size,
        max_queries=50000,
        max_inactive_connection_lifetime=300.0,
        loop=None,
        connection_class=asyncpg.Connection,
        record_class=asyncpg.Record,
    )
    await pool
    _live_pools.add(pool)
    return pool
