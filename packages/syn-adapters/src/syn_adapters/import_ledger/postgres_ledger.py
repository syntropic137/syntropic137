"""Durable delegate import ledger (#933, #936).

Records, per (execution_id, harness_session_id), the CUMULATIVE usage this
execution has already been charged for. A later import compares its own
cumulative figure against the mark and bills only the difference.

Two properties matter and both live in SQL rather than in Python, because
Python cannot make them atomic across concurrent importers:

* the mark only ever RISES (``GREATEST`` per bucket), so a stale import
  carrying an older cumulative figure cannot lower it;
* the read-write-commit window is serialized per session by an advisory lock,
  because the charge is written to a different store in between.
"""

from __future__ import annotations

import contextlib
import contextvars
import hashlib
import logging
import struct
from typing import TYPE_CHECKING, Protocol

from syn_domain.contexts.agent_sessions import BilledUsage

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

logger = logging.getLogger(__name__)

__all__ = ["PostgresImportLedger"]

#: The connection currently holding this session's advisory lock, if any.
#:
#: `guard()` holds a pooled connection for the whole claim window. If the reads
#: and writes inside it acquired their OWN connections, N concurrent imports
#: would each hold one connection and wait for a second - and with a pool of 5,
#: five of them deadlock permanently with the cost path wedged. So the guarded
#: work reuses the guard's connection.
#:
#: A ContextVar rather than an attribute because one adapter instance is shared
#: process-wide (it is a singleton in the wiring): an attribute would leak one
#: task's connection into another's queries.
_guarded_conn: contextvars.ContextVar[AsyncConnection | None] = contextvars.ContextVar(
    "syn_import_ledger_guarded_conn", default=None
)


CREATE_TABLE_SQL = """
    CREATE TABLE IF NOT EXISTS delegate_import_ledger (
        execution_id           TEXT   NOT NULL,
        harness_session_id     TEXT   NOT NULL,
        uncached_input_tokens  BIGINT NOT NULL DEFAULT 0,
        cache_read_tokens      BIGINT NOT NULL DEFAULT 0,
        cache_creation_tokens  BIGINT NOT NULL DEFAULT 0,
        output_tokens          BIGINT NOT NULL DEFAULT 0,
        updated_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
        PRIMARY KEY (execution_id, harness_session_id)
    );
"""

ALREADY_BILLED_SQL = """
    SELECT uncached_input_tokens, cache_read_tokens,
           cache_creation_tokens, output_tokens
    FROM delegate_import_ledger
    WHERE execution_id = $1 AND harness_session_id = $2;
"""

#: The mark rises, never falls. Without GREATEST an import that read an older
#: transcript could commit 40 after another committed 50, and the next read of
#: 50 would bill the 10 difference a second time.
RECORD_BILLED_SQL = """
    INSERT INTO delegate_import_ledger AS l (
        execution_id, harness_session_id,
        uncached_input_tokens, cache_read_tokens,
        cache_creation_tokens, output_tokens
    )
    VALUES ($1, $2, $3, $4, $5, $6)
    ON CONFLICT (execution_id, harness_session_id) DO UPDATE SET
        uncached_input_tokens = GREATEST(l.uncached_input_tokens, EXCLUDED.uncached_input_tokens),
        cache_read_tokens     = GREATEST(l.cache_read_tokens,     EXCLUDED.cache_read_tokens),
        cache_creation_tokens = GREATEST(l.cache_creation_tokens, EXCLUDED.cache_creation_tokens),
        output_tokens         = GREATEST(l.output_tokens,         EXCLUDED.output_tokens),
        updated_at            = now();
"""


class _Row(Protocol):
    def __getitem__(self, key: str) -> int: ...


class AsyncConnection(Protocol):
    async def execute(self, query: str, *args: object) -> object: ...
    async def fetchrow(self, query: str, *args: object) -> _Row | None: ...


class _PoolAcquireContext(Protocol):
    async def __aenter__(self) -> AsyncConnection: ...
    async def __aexit__(self, *exc: object) -> None: ...


class AsyncConnectionPool(Protocol):
    def acquire(self) -> _PoolAcquireContext: ...


def _advisory_key(execution_id: str, harness_session_id: str) -> int:
    """A stable signed 64-bit key for ``pg_advisory_lock``.

    Postgres advisory locks are integers, so the pair has to be hashed. Python's
    ``hash()`` is salted per process and would give two API replicas DIFFERENT
    lock keys for the same session - which is exactly the case the lock exists
    to serialize - so this uses a stable digest instead.
    """
    digest = hashlib.blake2b(
        f"{execution_id}\x00{harness_session_id}".encode(), digest_size=8
    ).digest()
    return struct.unpack(">q", digest)[0]


class PostgresImportLedger:
    """Postgres-backed ledger. Survives restarts; safe across replicas."""

    def __init__(self, pool: AsyncConnectionPool) -> None:
        self._pool = pool
        self._table_created = False

    async def ensure_ready(self) -> None:
        """Create the table NOW and let failures surface at startup.

        Lazy creation on first import is not good enough here. The import path
        is deliberately fail-open - it must never turn agent work that
        succeeded into a phase that failed - so a DDL or permission failure
        inside it is logged and swallowed, and the execution proceeds billing
        as if there were no ledger at all. The operator sees healthy.

        Same lesson as the MinIO buckets in ADR-012: create eagerly at startup,
        because the first real use is the worst place to discover the store is
        unusable.
        """
        await self._ensure_table()

    async def _ensure_table(self) -> None:
        if self._table_created:
            return
        async with self._pool.acquire() as conn:
            await conn.execute(CREATE_TABLE_SQL)
        self._table_created = True
        logger.info("Ensured delegate_import_ledger table exists")

    @contextlib.asynccontextmanager
    async def _connection(self) -> AsyncIterator[AsyncConnection]:
        """The guard's connection when inside one, otherwise a fresh acquire."""
        bound = _guarded_conn.get()
        if bound is not None:
            yield bound
            return
        async with self._pool.acquire() as conn:
            yield conn

    async def already_billed(self, execution_id: str, harness_session_id: str) -> BilledUsage:
        await self._ensure_table()
        async with self._connection() as conn:
            row = await conn.fetchrow(ALREADY_BILLED_SQL, execution_id, harness_session_id)
        if row is None:
            return BilledUsage()
        return BilledUsage(
            uncached_input_tokens=row["uncached_input_tokens"],
            cache_read_tokens=row["cache_read_tokens"],
            cache_creation_tokens=row["cache_creation_tokens"],
            output_tokens=row["output_tokens"],
        )

    async def record_billed(
        self, execution_id: str, harness_session_id: str, billed: BilledUsage
    ) -> None:
        await self._ensure_table()
        async with self._connection() as conn:
            await conn.execute(
                RECORD_BILLED_SQL,
                execution_id,
                harness_session_id,
                billed.uncached_input_tokens,
                billed.cache_read_tokens,
                billed.cache_creation_tokens,
                billed.output_tokens,
            )

    @contextlib.asynccontextmanager
    async def guard(self, execution_id: str, harness_session_id: str) -> AsyncIterator[None]:
        """Hold a session-level advisory lock for the whole import.

        Session-level rather than transaction-level (`pg_advisory_xact_lock`)
        because the charge itself is written through a different store while
        this is held, so there is no single transaction to scope it to.

        The unlock is in a `finally` and on the SAME connection that took the
        lock: a session-level advisory lock belongs to its connection, and
        releasing it from another pool connection silently does nothing while
        the real lock is held until that connection is recycled.
        """
        await self._ensure_table()
        key = _advisory_key(execution_id, harness_session_id)
        async with self._pool.acquire() as conn:
            await conn.execute("SELECT pg_advisory_lock($1);", key)
            token = _guarded_conn.set(conn)
            try:
                yield
            finally:
                _guarded_conn.reset(token)
                await conn.execute("SELECT pg_advisory_unlock($1);", key)
