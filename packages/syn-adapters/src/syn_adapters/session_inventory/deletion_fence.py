"""Installation-wide deletion fence, linearizing tombstones with byte consumers.

A deletion request holds the exclusive side while it writes the archive marker
and commits the SQL tombstone. Every path that could deliver or derive facts
from bytes (replica drain, historical backfill) holds the shared side across
its tombstone check and the use of the bytes. So each such use either finished
before the request took effect, or observes the tombstone. PostgreSQL advisory
locks span processes and are released if a holder's connection dies.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from .database import Connection, Pool

_KEY = "syn-transcript-deletion-fence/1:"
_LANE = "syn-capture-deletion-lane/1:"


class DeletionFence:
    def __init__(self, pool: Pool, source_instance_id: str) -> None:
        if not source_instance_id.strip():
            raise ValueError("deletion fence requires an installation identity")
        self._pool, self._key = pool, _KEY + source_instance_id

    @asynccontextmanager
    async def exclusive(self) -> AsyncIterator[Connection]:
        """Held by tombstone writers; waits for in-flight shared holders."""
        async with self._pool.acquire() as conn:
            await conn.execute("SELECT pg_advisory_lock(hashtextextended($1,0))", self._key)
            try:
                yield conn
            finally:
                await conn.execute("SELECT pg_advisory_unlock(hashtextextended($1,0))", self._key)

    @asynccontextmanager
    async def shared(self) -> AsyncIterator[Connection]:
        """Held by byte consumers across their tombstone check and the byte use."""
        async with self._pool.acquire() as conn:
            await conn.execute("SELECT pg_advisory_lock_shared(hashtextextended($1,0))", self._key)
            try:
                yield conn
            finally:
                await conn.execute(
                    "SELECT pg_advisory_unlock_shared(hashtextextended($1,0))", self._key
                )


async def lock_tombstones_xact(conn: Connection, source_instance_id: str) -> None:
    """Transaction-scoped exclusive side, for batch tombstone writers (retention)."""
    await conn.execute(
        "SELECT pg_advisory_xact_lock(hashtextextended($1,0))", _KEY + source_instance_id
    )


async def try_deletion_lane(conn: Connection, source: str, destination: str) -> bool:
    """One replica deletion in flight per destination, so acks are attributable."""
    acquired = await conn.fetchval(
        "SELECT pg_try_advisory_xact_lock(hashtextextended($1,0))::text",
        _LANE + source + ":" + destination,
    )
    return acquired == "true"
