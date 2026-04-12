"""Postgres-backed dedup adapter — durable across restarts.

See ADR-060: Restart-safe trigger deduplication.

Uses INSERT ... ON CONFLICT DO NOTHING for atomic check-and-mark.
Replaces Redis as the primary dedup backend for correctness;
Redis can still be used as an optional fast cache layer.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

logger = logging.getLogger(__name__)

_DEFAULT_TTL_DAYS = 7
_CLEANUP_INTERVAL_SECONDS = 3600  # 1 hour


class _Row(Protocol):
    """Protocol for database row objects (asyncpg Record compatible)."""

    def __getitem__(self, key: str) -> object: ...


@runtime_checkable
class AsyncConnection(Protocol):
    """Protocol for async database connections (asyncpg-compatible)."""

    async def execute(self, query: str, *args: object) -> str: ...
    async def fetchrow(self, query: str, *args: object) -> _Row | None: ...


@runtime_checkable
class AsyncConnectionPool(Protocol):
    """Protocol for async connection pools (asyncpg-compatible)."""

    @asynccontextmanager
    def acquire(self) -> AsyncIterator[AsyncConnection]: ...


CREATE_TABLE_SQL = """
    CREATE TABLE IF NOT EXISTS dedup_keys (
        key TEXT PRIMARY KEY,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
"""

# INSERT returns the key if it was inserted (new); returns nothing if conflict (duplicate).
IS_DUPLICATE_SQL = """
    INSERT INTO dedup_keys (key) VALUES ($1)
    ON CONFLICT (key) DO NOTHING
    RETURNING key;
"""

MARK_SEEN_SQL = """
    INSERT INTO dedup_keys (key) VALUES ($1)
    ON CONFLICT (key) DO NOTHING;
"""

CLEANUP_SQL = """
    DELETE FROM dedup_keys
    WHERE created_at < now() - make_interval(days => $1);
"""


class PostgresDedupAdapter:
    """Postgres-backed dedup using INSERT ON CONFLICT.

    Implements :class:`~syn_domain.contexts.github.slices.event_pipeline.dedup_port.DedupPort`.

    Durable across restarts — keys survive container restarts because
    TimescaleDB is backed by a persistent Docker volume.
    """

    def __init__(
        self,
        pool: AsyncConnectionPool,
        ttl_days: int = _DEFAULT_TTL_DAYS,
    ) -> None:
        self._pool = pool
        self._ttl_days = ttl_days
        self._table_created = False
        self._cleanup_task: asyncio.Task[None] | None = None

    async def _ensure_table(self) -> None:
        """Ensure the dedup_keys table exists (lazy creation)."""
        if self._table_created:
            return
        async with self._pool.acquire() as conn:
            await conn.execute(CREATE_TABLE_SQL)
            self._table_created = True
            logger.info("Ensured dedup_keys table exists")

        # Run initial cleanup and start periodic cleanup
        await self._cleanup_expired()
        self._cleanup_task = asyncio.create_task(
            self._periodic_cleanup(),
            name="dedup-key-cleanup",
        )

    async def is_duplicate(self, dedup_key: str) -> bool:
        """Return ``True`` if this key was already seen (duplicate).

        Atomic check-and-mark: INSERT succeeds (returns row) for new keys,
        does nothing (returns None) for existing keys.
        """
        await self._ensure_table()
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(IS_DUPLICATE_SQL, dedup_key)
        # If row is returned, the INSERT succeeded → key is NEW (not duplicate)
        # If row is None, ON CONFLICT fired → key already existed (duplicate)
        return row is None

    async def mark_seen(self, dedup_key: str) -> None:
        """Explicitly mark a key as seen."""
        await self._ensure_table()
        async with self._pool.acquire() as conn:
            await conn.execute(MARK_SEEN_SQL, dedup_key)

    async def _cleanup_expired(self) -> None:
        """Delete dedup keys older than the TTL."""
        try:
            async with self._pool.acquire() as conn:
                result = await conn.execute(CLEANUP_SQL, self._ttl_days)
                # asyncpg returns "DELETE N" string
                count = result.split()[-1] if result else "0"
                if count != "0":
                    logger.info("Cleaned up %s expired dedup keys", count)
        except Exception:
            logger.warning("Failed to cleanup expired dedup keys", exc_info=True)

    async def _periodic_cleanup(self) -> None:
        """Run cleanup periodically in the background."""
        while True:
            await asyncio.sleep(_CLEANUP_INTERVAL_SECONDS)
            await self._cleanup_expired()

    async def shutdown(self) -> None:
        """Cancel the periodic cleanup task."""
        if self._cleanup_task is not None:
            self._cleanup_task.cancel()
            self._cleanup_task = None
