"""Per-run inventory scheduling guard over a Postgres advisory lock (#1534, #2254).

A session-level lock on its own pooled connection, taken with one
``pg_try_advisory_lock`` and never waited on: a manager that loses skips the run
this tick, leaving its wakeup in the outbox. The lock spans processes and is
freed if the holder's connection dies, so a crashed manager cannot strand a run.

While held, the run's ``session_inventory_schedules`` row is read and written on
that same connection. The rest of the critical section (job projection, inventory
head, outbox acknowledgement) acquires from the pool while the guard's
connection is out, so the pool must have room for one more (#2254).
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from syn_adapters.advisory_locks import inventory_schedule_lock_key, try_session_advisory_lock

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from syn_domain.contexts.agent_sessions import RunIdentity

    from .database import Connection, Pool

# The guard's own connection plus one for each read or write made while it is held.
MIN_POOL_SIZE = 2


class PostgresInventorySchedulingGuard:
    def __init__(self, pool: Pool) -> None:
        # Refused here, at wiring, because the failure is otherwise a hang: the
        # first pool acquire inside the held guard waits for a connection only
        # the guard can release.
        if pool.get_max_size() < MIN_POOL_SIZE:
            raise ValueError(
                f"inventory scheduling needs a pool of at least {MIN_POOL_SIZE} connections, "
                f"got {pool.get_max_size()}: the guard holds one while the schedule acquires another"
            )
        self._pool = pool

    @asynccontextmanager
    async def hold(self, run: RunIdentity) -> AsyncIterator[_PostgresSchedule | None]:
        key = inventory_schedule_lock_key(run.source_instance_id, run.execution_id)
        async with self._pool.acquire() as conn, try_session_advisory_lock(conn, key) as held:
            yield _PostgresSchedule(conn, run) if held else None


class _PostgresSchedule:
    def __init__(self, conn: Connection, run: RunIdentity) -> None:
        self._conn, self._run = conn, run

    async def last_scheduled(self) -> str | None:
        return await self._conn.fetchval(
            """SELECT job_id FROM session_inventory_schedules
            WHERE source_instance_id=$1 AND execution_id=$2""",
            self._run.source_instance_id,
            self._run.execution_id,
        )

    async def record_scheduled(self, job_id: str) -> None:
        await self._conn.execute(
            """INSERT INTO session_inventory_schedules (source_instance_id,execution_id,job_id)
            VALUES ($1,$2,$3) ON CONFLICT (source_instance_id,execution_id)
            DO UPDATE SET job_id=EXCLUDED.job_id""",
            self._run.source_instance_id,
            self._run.execution_id,
            job_id,
        )
