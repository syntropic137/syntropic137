"""Persistent poller cursor store - survives restarts.

See ADR-060: Restart-safe trigger deduplication.

Implements the ESP ``CursorStore`` protocol for persisting GitHub Events
API ETags and last-seen event IDs in Postgres. On startup, the poller
loads stored ETags and sends ``If-None-Match`` headers to GitHub,
avoiding re-fetching events it already processed.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from event_sourcing.core.historical_poller import CursorData

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

logger = logging.getLogger(__name__)


class _Row(Protocol):
    """Protocol for database row objects (asyncpg Record compatible)."""

    def __getitem__(self, key: str) -> object: ...


@runtime_checkable
class AsyncConnection(Protocol):
    """Protocol for async database connections (asyncpg-compatible)."""

    async def execute(self, query: str, *args: object) -> str: ...
    async def fetchrow(self, query: str, *args: object) -> _Row | None: ...
    async def fetch(self, query: str, *args: object) -> list[_Row]: ...


@runtime_checkable
class AsyncConnectionPool(Protocol):
    """Protocol for async connection pools (asyncpg-compatible)."""

    @asynccontextmanager
    def acquire(self) -> AsyncIterator[AsyncConnection]: ...


CREATE_TABLE_SQL = """
    CREATE TABLE IF NOT EXISTS poller_cursors (
        repo TEXT PRIMARY KEY,
        etag TEXT NOT NULL DEFAULT '',
        last_event_id TEXT NOT NULL DEFAULT '',
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
"""

LOAD_CURSOR_SQL = """
    SELECT repo, etag, last_event_id
    FROM poller_cursors
    WHERE repo = $1;
"""

SAVE_CURSOR_SQL = """
    INSERT INTO poller_cursors (repo, etag, last_event_id, updated_at)
    VALUES ($1, $2, $3, now())
    ON CONFLICT (repo) DO UPDATE SET
        etag = EXCLUDED.etag,
        last_event_id = EXCLUDED.last_event_id,
        updated_at = EXCLUDED.updated_at;
"""

LOAD_ALL_SQL = """
    SELECT repo, etag, last_event_id
    FROM poller_cursors;
"""


class PostgresPollerCursorStore:
    """Postgres-backed CursorStore for production use.

    Implements the ESP ``CursorStore`` protocol. Persists ETag and
    last-seen event ID per repository. On startup, the poller loads
    stored ETags and sends ``If-None-Match`` headers to GitHub,
    avoiding re-fetching events it already processed.

    CursorData mapping:
    - ``value`` = ETag string
    - ``metadata["last_event_id"]`` = newest event ID seen
    """

    def __init__(self, pool: AsyncConnectionPool) -> None:
        self._pool = pool
        self._table_created = False

    async def _ensure_table(self) -> None:
        """Ensure the poller_cursors table exists (lazy creation)."""
        if self._table_created:
            return
        async with self._pool.acquire() as conn:
            await conn.execute(CREATE_TABLE_SQL)
            self._table_created = True
            logger.info("Ensured poller_cursors table exists")

    async def load(self, source_key: str) -> CursorData | None:
        """Load the stored cursor for a source.

        Returns None if no cursor has been saved for this source.
        """
        await self._ensure_table()
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(LOAD_CURSOR_SQL, source_key)
        if row is None:
            return None
        return CursorData(
            value=str(row["etag"]),
            metadata={"last_event_id": str(row["last_event_id"])},
        )

    async def save(self, source_key: str, cursor: CursorData) -> None:
        """Save or update the cursor for a source."""
        await self._ensure_table()
        last_event_id = (cursor.metadata or {}).get("last_event_id", "")
        async with self._pool.acquire() as conn:
            await conn.execute(SAVE_CURSOR_SQL, source_key, cursor.value, last_event_id)
        logger.debug(
            "Saved poller cursor for %s (etag=%s, last_event_id=%s)",
            source_key,
            cursor.value[:16] + "..." if len(cursor.value) > 16 else cursor.value,
            last_event_id,
        )

    async def load_all(self) -> dict[str, CursorData]:
        """Load all stored cursors (used on startup to pre-populate ETags)."""
        await self._ensure_table()
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(LOAD_ALL_SQL)
        cursors: dict[str, CursorData] = {}
        for row in rows:
            source_key = str(row["repo"])
            cursors[source_key] = CursorData(
                value=str(row["etag"]),
                metadata={"last_event_id": str(row["last_event_id"])},
            )
        logger.info("Loaded %d poller cursor(s) from database", len(cursors))
        return cursors
