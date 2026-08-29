"""The Postgres ledger's own tests (#933, #936).

A codex review found the adapter had NONE: every ledger test drove the
in-memory implementation, so the code that actually runs in production was
unexercised. These use a fake pool with a BOUNDED connection count, which is
what makes the deadlock reproducible without a real database - the bound is the
whole hazard.
"""

from __future__ import annotations

import asyncio

import pytest

from syn_adapters.import_ledger import PostgresImportLedger
from syn_domain.contexts.agent_sessions import BilledUsage

pytestmark = pytest.mark.unit


class _FakeConn:
    def __init__(self, pool: _FakePool) -> None:
        self._pool = pool
        self.rows: dict[tuple[str, str], dict[str, int]] = pool.rows

    async def execute(self, query: str, *args: object) -> None:
        self._pool.queries.append(query.strip().split("\n")[0])
        if "pg_advisory_lock" in query:
            await self._pool.advisory_acquire(int(args[0]))  # type: ignore[arg-type]
        elif "pg_advisory_unlock" in query:
            self._pool.advisory_release(int(args[0]))  # type: ignore[arg-type]
        elif query.strip().startswith("INSERT INTO delegate_import_ledger"):
            key = (str(args[0]), str(args[1]))
            new = {
                "uncached_input_tokens": int(args[2]),  # type: ignore[arg-type]
                "cache_read_tokens": int(args[3]),  # type: ignore[arg-type]
                "cache_creation_tokens": int(args[4]),  # type: ignore[arg-type]
                "output_tokens": int(args[5]),  # type: ignore[arg-type]
            }
            old = self.rows.get(key)
            # Stands in for GREATEST. If the SQL loses it, this fake still
            # applies it - so the fake must NOT be the thing under test; the
            # SQL text assertion below is.
            self.rows[key] = new if old is None else {k: max(old[k], new[k]) for k in new}

    async def fetchrow(self, query: str, *args: object) -> dict[str, int] | None:
        self._pool.queries.append(query.strip().split("\n")[0])
        return self.rows.get((str(args[0]), str(args[1])))


class _FakePool:
    """A pool with a hard connection limit, like the real one."""

    def __init__(self, size: int = 5) -> None:
        self._sem = asyncio.Semaphore(size)
        self.rows: dict[tuple[str, str], dict[str, int]] = {}
        self.queries: list[str] = []
        self._locks: dict[int, asyncio.Lock] = {}
        self._held: dict[int, asyncio.Lock] = {}
        self.peak_concurrent = 0
        self._live = 0

    async def advisory_acquire(self, key: int) -> None:
        lock = self._locks.setdefault(key, asyncio.Lock())
        await lock.acquire()
        self._held[key] = lock

    def advisory_release(self, key: int) -> None:
        lock = self._held.pop(key, None)
        if lock is not None and lock.locked():
            lock.release()

    def acquire(self) -> _FakeAcquire:
        return _FakeAcquire(self)


class _FakeAcquire:
    """The pool's `acquire()` context manager, with a real type.

    Not `Any`: the whole point of these tests is that a connection is or is not
    taken, and an untyped handle would hide a mistake in the very object under
    measurement.
    """

    def __init__(self, pool: _FakePool) -> None:
        self._pool = pool

    async def __aenter__(self) -> _FakeConn:
        await self._pool._sem.acquire()
        self._pool._live += 1
        self._pool.peak_concurrent = max(self._pool.peak_concurrent, self._pool._live)
        return _FakeConn(self._pool)

    async def __aexit__(self, *exc: object) -> None:
        self._pool._live -= 1
        self._pool._sem.release()


class TestTheGuardDoesNotExhaustThePool:
    """The finding: guard() held a connection while the guarded reads and
    writes acquired MORE. N concurrent imports each hold one and wait for a
    second; with a pool of N they wait forever and the cost path wedges."""

    async def test_concurrent_guarded_imports_do_not_deadlock(self) -> None:
        pool = _FakePool(size=2)
        ledger = PostgresImportLedger(pool)

        async def one(session: str) -> None:
            async with ledger.guard("exec-1", session):
                await ledger.already_billed("exec-1", session)
                await ledger.record_billed("exec-1", session, BilledUsage(output_tokens=5))

        # Four contenders through a pool of two. Every task needs a connection
        # for the guard AND for the work inside it; without reuse this never
        # returns.
        async with asyncio.timeout(5):
            await asyncio.gather(*(one(f"session-{i}") for i in range(4)))

    async def test_the_guarded_work_uses_the_guard_connection(self) -> None:
        """A pool of ONE proves reuse rather than merely enough headroom."""
        pool = _FakePool(size=1)
        ledger = PostgresImportLedger(pool)

        async with asyncio.timeout(5), ledger.guard("exec-1", "session-a"):
            await ledger.already_billed("exec-1", "session-a")
            await ledger.record_billed("exec-1", "session-a", BilledUsage(output_tokens=7))

        assert pool.peak_concurrent == 1, (
            f"the guarded work took a second connection (peak {pool.peak_concurrent}); "
            "with a full pool that is a deadlock"
        )


class TestTheAdvisoryLockIsReleased:
    async def test_it_is_released_when_the_body_raises(self) -> None:
        pool = _FakePool()
        ledger = PostgresImportLedger(pool)

        with pytest.raises(RuntimeError):
            async with ledger.guard("exec-1", "session-a"):
                raise RuntimeError("boom")

        # If the unlock were skipped, this would hang rather than fail.
        async with asyncio.timeout(5), ledger.guard("exec-1", "session-a"):
            pass

    async def test_unlock_runs_on_the_same_connection_that_locked(self) -> None:
        """A session-level advisory lock belongs to its connection. Releasing
        it from a different pooled connection silently does nothing while the
        real lock stays held until that connection is recycled."""
        pool = _FakePool()
        ledger = PostgresImportLedger(pool)
        async with ledger.guard("exec-1", "session-a"):
            pass
        lock_at = pool.queries.index("SELECT pg_advisory_lock($1);")
        unlock_at = pool.queries.index("SELECT pg_advisory_unlock($1);")
        assert pool.peak_concurrent == 1, "lock and unlock used different connections"
        assert lock_at < unlock_at


class TestTheSqlItself:
    """The in-memory adapter's monotonicity tests cannot see this SQL, so the
    Postgres mark could lose GREATEST with every existing test still green."""

    def test_the_upsert_raises_the_mark_per_bucket(self) -> None:
        import re

        from syn_adapters.import_ledger.postgres_ledger import RECORD_BILLED_SQL

        # The SQL is column-aligned with padding, so match on structure rather
        # than on exact spacing - otherwise a reformat breaks a correctness test.
        sql = re.sub(r"\s+", " ", RECORD_BILLED_SQL)

        for bucket in (
            "uncached_input_tokens",
            "cache_read_tokens",
            "cache_creation_tokens",
            "output_tokens",
        ):
            assert f"GREATEST(l.{bucket}, EXCLUDED.{bucket})" in sql, (
                f"{bucket} is written unconditionally; a stale import can lower the mark "
                "and the next read bills the difference again"
            )

    def test_the_advisory_key_is_stable_across_processes(self) -> None:
        """`hash()` is salted per process, so two API replicas would derive
        DIFFERENT lock keys for the same session - exactly the case the lock
        exists to serialize."""
        from syn_adapters.import_ledger.postgres_ledger import _advisory_key

        assert _advisory_key("exec-1", "s") == 232987609242220664
        assert -(2**63) <= _advisory_key("exec-1", "s") < 2**63
