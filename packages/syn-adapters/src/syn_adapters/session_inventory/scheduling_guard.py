"""Per-run inventory scheduling guard over a Postgres advisory lock (#1534).

A session-level lock on its own pooled connection, taken with one
``pg_try_advisory_lock`` and never waited on: a manager that loses skips the run
this tick, leaving its wakeup in the outbox. The lock spans processes and is
freed if the holder's connection dies, so a crashed manager cannot strand a run.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from syn_adapters.advisory_locks import inventory_schedule_lock_key, try_session_advisory_lock

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from syn_domain.contexts.agent_sessions import RunIdentity

    from .database import Pool


class PostgresInventorySchedulingGuard:
    def __init__(self, pool: Pool) -> None:
        self._pool = pool

    @asynccontextmanager
    async def hold(self, run: RunIdentity) -> AsyncIterator[bool]:
        key = inventory_schedule_lock_key(run.source_instance_id, run.execution_id)
        async with self._pool.acquire() as conn, try_session_advisory_lock(conn, key) as held:
            yield held
