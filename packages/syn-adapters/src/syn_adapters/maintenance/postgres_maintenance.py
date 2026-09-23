"""Durable maintenance mode, backed by Postgres (#1387, ADR-060).

One row, because there is one system-wide answer to "may an execution start".
The row is read on every check - no caching anywhere in this adapter - so a
freshly started API container reads what the operator set before the swap
rather than coming up permissive.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from syn_domain.contexts._shared import MaintenanceMode

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

logger = logging.getLogger(__name__)

__all__ = ["PostgresMaintenanceAdapter"]


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


#: ``singleton`` pins the table to exactly one row. Without the CHECK a second
#: row could be inserted and the read would then depend on which one came back
#: first - two answers to a question that has one.
CREATE_TABLE_SQL = """
    CREATE TABLE IF NOT EXISTS maintenance_mode (
        singleton  BOOLEAN     PRIMARY KEY DEFAULT TRUE CHECK (singleton),
        active     BOOLEAN     NOT NULL,
        reason     TEXT        NOT NULL DEFAULT '',
        since      TIMESTAMPTZ,
        actor      TEXT        NOT NULL DEFAULT '',
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
"""

CURRENT_SQL = """
    SELECT active, reason, since, actor
    FROM maintenance_mode
    WHERE singleton = TRUE;
"""

#: The write is the whole durability guarantee: it returns only once committed,
#: so the operator's call cannot come back while admission is still open.
SET_MODE_SQL = """
    INSERT INTO maintenance_mode (singleton, active, reason, since, actor, updated_at)
    VALUES (TRUE, $1, $2, $3, $4, now())
    ON CONFLICT (singleton) DO UPDATE SET
        active     = EXCLUDED.active,
        reason     = EXCLUDED.reason,
        since      = EXCLUDED.since,
        actor      = EXCLUDED.actor,
        updated_at = now();
"""


class PostgresMaintenanceAdapter:
    """Postgres-backed maintenance mode.

    Implements
    :class:`~syn_domain.contexts._shared.maintenance.MaintenancePort`.
    """

    def __init__(self, pool: AsyncConnectionPool) -> None:
        self._pool = pool
        self._table_created = False

    async def _ensure_table(self) -> None:
        if self._table_created:
            return
        async with self._pool.acquire() as conn:
            await conn.execute(CREATE_TABLE_SQL)
        self._table_created = True
        logger.info("Ensured maintenance_mode table exists")

    async def current(self) -> MaintenanceMode:
        """Read the stored state. Never cached - see the module docstring."""
        await self._ensure_table()
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(CURRENT_SQL)
        if row is None:
            return MaintenanceMode()
        since = row["since"]
        return MaintenanceMode(
            active=bool(row["active"]),
            reason=str(row["reason"] or ""),
            since=since if isinstance(since, datetime) else None,
            actor=str(row["actor"] or ""),
        )

    async def set_mode(self, *, active: bool, reason: str, actor: str) -> MaintenanceMode:
        """Persist the state, then return it. Committed before this returns."""
        await self._ensure_table()
        mode = MaintenanceMode(
            active=active,
            reason=reason,
            since=datetime.now(UTC) if active else None,
            actor=actor,
        )
        async with self._pool.acquire() as conn:
            await conn.execute(SET_MODE_SQL, mode.active, mode.reason, mode.since, mode.actor)
        return mode
