"""Advisory lock keys shared by every schema step that runs at startup, and per run.

Postgres advisory locks are database-wide integers, so two keys that collide
would serialise unrelated steps, or worse, let one step release another's lock.
Every startup key lives here, derived from a name, so a new one is checked
against the rest in one place (``test_advisory_locks``) and a row in
``pg_locks`` can be traced back to its line.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import struct
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


def advisory_lock_key(name: str) -> int:
    """A stable signed 64-bit key for ``name``: the same in every process."""
    return struct.unpack(">q", hashlib.blake2b(name.encode(), digest_size=8).digest())[0]


# The day rollup's schema transaction (#1371). See events/schema.py.
ROLLUP_SCHEMA_LOCK_KEY: int = advisory_lock_key("agent_event_day_rollup:schema")
# Spans the day rollup transaction AND the concurrent index build after it (#1906).
ROLLUP_STARTUP_LOCK_KEY: int = advisory_lock_key("agent_event_day_rollup:startup")
USAGE_ROLLUP_SCHEMA_LOCK_KEY: int = advisory_lock_key("agent_usage_rollup:schema")
# The Run Queue's schema.sql, applied by the api and every executor at once (#1965).
RUN_QUEUE_SCHEMA_LOCK_KEY: int = advisory_lock_key("execution_run_queue:schema")



def inventory_schedule_lock_key(source_instance_id: str, execution_id: str) -> int:
    """The key one run's inventory scheduling holds across check + schedule (#1534).

    One key per run, not one for all scheduling, so managers working on
    different runs never skip each other. Derived from an encoding that cannot
    be mistaken for a startup name, so it cannot land on one of the keys above.
    """
    return advisory_lock_key(
        json.dumps(("session_inventory:schedule", source_instance_id, execution_id))
    )


TRY_SESSION_LOCK_SQL = "SELECT pg_try_advisory_lock($1)"
SESSION_UNLOCK_SQL = "SELECT pg_advisory_unlock($1)"

# How often a process that lost a startup lock asks again. Startup only.
STARTUP_LOCK_RETRY_SECONDS = 0.1


class LockConnection(Protocol):
    async def execute(self, query: str, *args: object) -> object: ...
    async def fetchval(self, query: str, *args: object) -> object: ...


@asynccontextmanager
async def session_advisory_lock(
    conn: LockConnection, key: int, *, retry_seconds: float = STARTUP_LOCK_RETRY_SECONDS
) -> AsyncIterator[None]:
    """Hold the session-level advisory lock ``key`` for the block.

    Taken by retrying pg_try_advisory_lock rather than by blocking in
    pg_advisory_lock: a backend blocked inside a statement holds a snapshot, and
    CREATE INDEX CONCURRENTLY waits for every older snapshot, so a blocked
    waiter deadlocks with a holder that builds one (#1906, #1934). Between
    attempts the waiter holds none. Callers must not hold a transaction open
    around this either, for the same reason.
    """
    while not await conn.fetchval(TRY_SESSION_LOCK_SQL, key):
        await asyncio.sleep(retry_seconds)
    try:
        yield
    finally:
        # Session locks survive the transaction, so release promptly here.
        # If this cannot run (cancelled mid-acquire, broken connection), the
        # pool's reset (pg_advisory_unlock_all) or the session ending frees it.
        await conn.execute(SESSION_UNLOCK_SQL, key)


@asynccontextmanager
async def try_session_advisory_lock(conn: LockConnection, key: int) -> AsyncIterator[bool]:
    """Ask ONCE for the session-level advisory lock ``key``; yield whether it is held.

    For per-tick work that skips what someone else is doing rather than
    waiting on it (#1534), unlike ``session_advisory_lock``, which retries.
    Released on exit only if it was taken.
    """
    held = bool(await conn.fetchval(TRY_SESSION_LOCK_SQL, key))
    try:
        yield held
    finally:
        if held:
            await conn.execute(SESSION_UNLOCK_SQL, key)
