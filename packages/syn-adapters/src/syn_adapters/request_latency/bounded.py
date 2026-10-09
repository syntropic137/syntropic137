"""One connection, one operation, every step under a deadline (ADR-075).

``async with pool.acquire()`` cannot be bounded from outside: asyncpg shields
the release (and the connection reset inside it) from cancellation and gives
it no timeout, so a stalled reset outlives any ``asyncio.timeout`` around the
block and later holds up ``pool.close()``. So acquire, operate and release are
three separate bounded steps here. A release that overruns terminates the
connection, which asyncpg's pending release then sees as closed and finishes
at once: nothing is left waiting on the server.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

logger = logging.getLogger(__name__)


class _Connection(Protocol):
    def terminate(self) -> None: ...


class BoundedPool[C: _Connection](Protocol):
    """The part of ``asyncpg.Pool`` this module uses."""

    async def acquire(self, *, timeout: float | None = None) -> C: ...

    async def release(self, connection: C, *, timeout: float | None = None) -> None: ...


@dataclass(frozen=True, slots=True)
class Bounded[T]:
    value: T
    released: bool
    """False when the connection had to be terminated because releasing it overran."""


def _abandon[C: _Connection](pool: BoundedPool[C], conn: C) -> None:
    """Terminate ``conn`` and hand it back without waiting (a closed one releases at once)."""
    with contextlib.suppress(Exception):
        conn.terminate()
    task = asyncio.ensure_future(pool.release(conn))
    task.add_done_callback(lambda t: t.cancelled() or t.exception())


async def run_bounded[C: _Connection, T](
    pool: BoundedPool[C], timeout_s: float, op: Callable[[C], Awaitable[T]]
) -> Bounded[T]:
    """``op`` on one pooled connection, each step bounded by ``timeout_s``.

    Raises ``TimeoutError`` if acquiring or ``op`` overruns, and whatever ``op``
    raises; the connection is terminated on every such path, and on
    cancellation, so it never goes back to the pool mid-operation.
    """
    conn = await pool.acquire(timeout=timeout_s)
    try:
        value = await asyncio.wait_for(op(conn), timeout=timeout_s)
    except BaseException:
        _abandon(pool, conn)
        raise
    try:
        await asyncio.wait_for(pool.release(conn, timeout=timeout_s), timeout=timeout_s)
    except asyncio.CancelledError:
        _abandon(pool, conn)
        raise
    except Exception:
        logger.warning("request latency: connection release overran; terminated", exc_info=True)
        _abandon(pool, conn)
        return Bounded(value, released=False)
    return Bounded(value, released=True)
