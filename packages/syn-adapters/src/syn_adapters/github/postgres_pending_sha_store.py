"""Postgres-backed PendingSHAStore for check-run polling (#602).

Persists pending SHAs across restarts so check-run polling resumes
immediately without waiting for the next PR event.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

from syn_domain.contexts.github.slices.event_pipeline.pending_sha_port import PendingSHA

logger = logging.getLogger(__name__)


class _Row(Protocol):
    """Protocol for database row objects (asyncpg Record compatible)."""

    def __getitem__(self, key: str) -> object: ...


@runtime_checkable
class AsyncConnection(Protocol):
    """Protocol for async database connections (asyncpg-compatible)."""

    async def execute(self, query: str, *args: object) -> str: ...
    async def fetch(self, query: str, *args: object) -> list[_Row]: ...


@runtime_checkable
class AsyncConnectionPool(Protocol):
    """Protocol for async connection pools (asyncpg-compatible)."""

    @asynccontextmanager
    def acquire(self) -> AsyncIterator[AsyncConnection]: ...


_CREATE_TABLE_SQL = """
    CREATE TABLE IF NOT EXISTS pending_shas (
        repository TEXT NOT NULL,
        sha TEXT NOT NULL,
        pr_number INTEGER NOT NULL,
        branch TEXT NOT NULL,
        installation_id TEXT NOT NULL,
        registered_at TIMESTAMPTZ NOT NULL,
        PRIMARY KEY (repository, sha)
    );
"""

_REGISTER_SQL = """
    INSERT INTO pending_shas (repository, sha, pr_number, branch, installation_id, registered_at)
    VALUES ($1, $2, $3, $4, $5, $6)
    ON CONFLICT (repository, sha) DO NOTHING;
"""

_LIST_SQL = (
    "SELECT repository, sha, pr_number, branch, installation_id, registered_at FROM pending_shas;"
)

_REMOVE_SQL = "DELETE FROM pending_shas WHERE repository = $1 AND sha = $2;"

_CLEANUP_SQL = "DELETE FROM pending_shas WHERE registered_at < $1;"


class PostgresPendingSHAStore:
    """Postgres-backed PendingSHAStore - survives restarts.

    Implements :class:`~syn_domain.contexts.github.slices.event_pipeline.pending_sha_port.PendingSHAStore`.
    """

    def __init__(self, pool: AsyncConnectionPool) -> None:
        self._pool = pool
        self._table_created = False

    async def _ensure_table(self) -> None:
        if self._table_created:
            return
        async with self._pool.acquire() as conn:
            await conn.execute(_CREATE_TABLE_SQL)
            self._table_created = True
            logger.info("Ensured pending_shas table exists")

    async def register(self, pending: PendingSHA) -> None:
        """Register a SHA for check-run polling. No-op if already registered."""
        await self._ensure_table()
        async with self._pool.acquire() as conn:
            await conn.execute(
                _REGISTER_SQL,
                pending.repository,
                pending.sha,
                pending.pr_number,
                pending.branch,
                pending.installation_id,
                pending.registered_at,
            )

    async def list_pending(self) -> list[PendingSHA]:
        """Return all pending SHAs."""
        await self._ensure_table()
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(_LIST_SQL)
            return [
                PendingSHA(
                    repository=row["repository"],  # type: ignore[arg-type]
                    sha=row["sha"],  # type: ignore[arg-type]
                    pr_number=row["pr_number"],  # type: ignore[arg-type]
                    branch=row["branch"],  # type: ignore[arg-type]
                    installation_id=row["installation_id"],  # type: ignore[arg-type]
                    registered_at=row["registered_at"],  # type: ignore[arg-type]
                )
                for row in rows
            ]

    async def remove(self, repository: str, sha: str) -> None:
        """Remove a SHA after all check runs have completed."""
        await self._ensure_table()
        async with self._pool.acquire() as conn:
            await conn.execute(_REMOVE_SQL, repository, sha)

    async def cleanup_stale(self, max_age: timedelta) -> int:
        """Remove SHAs older than *max_age*. Returns count removed."""
        await self._ensure_table()
        cutoff = datetime.now(UTC) - max_age
        async with self._pool.acquire() as conn:
            result = await conn.execute(_CLEANUP_SQL, cutoff)
            # asyncpg returns "DELETE N" string
            count_str = result.split()[-1] if result else "0"
            return int(count_str)
