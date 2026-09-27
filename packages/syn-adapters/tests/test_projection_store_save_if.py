"""`save_if`: a projection write that lands only over the row it was decided on.

Verification of #1466 found the fork start's "read, decide, save" atomic only
inside one process manager, behind a lock the others do not share, so the
comparison and the write had to move into the store. These tests pin the two
properties a caller relies on:

* a row that moved on since it was read is not written over, and says so;
* a row that still holds what the caller read DOES match, compared as the model
  the caller read it as - otherwise a row that round-trips with any difference
  (a default filled in) would never match, and a caller that decides again
  after losing would never stop losing.

The Postgres store is driven against a connection double that holds one row and
records every statement, because no database is reachable where unit tests run.
What it can establish is the order of operations - the row is locked before it
is compared, and nothing is written after a mismatch - not Postgres's locking
itself.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
from pydantic import BaseModel

from syn_adapters.projection_stores.memory_store import InMemoryProjectionStore
from syn_adapters.projection_stores.postgres_store import PostgresProjectionStore

if TYPE_CHECKING:
    from pydantic import JsonValue

pytestmark = pytest.mark.unit

PROJECTION = "fork_start"
KEY = "exec-parent"


class _Record(BaseModel):
    status: str
    attempts: int = 0
    status_reason: str | None = None


PENDING = _Record(status="pending")
DISPATCHED = _Record(status="dispatched")
RETRYABLE = _Record(status="retryable", attempts=1, status_reason="blip")


class TestInMemory:
    async def test_writes_over_the_record_it_expected(self) -> None:
        store = InMemoryProjectionStore()
        await store.save(PROJECTION, KEY, PENDING.model_dump(mode="json"))

        assert await store.save_if(PROJECTION, KEY, DISPATCHED, expected=PENDING)
        assert await store.get(PROJECTION, KEY) == DISPATCHED.model_dump(mode="json")

    async def test_refuses_a_record_that_moved_on(self) -> None:
        store = InMemoryProjectionStore()
        await store.save(PROJECTION, KEY, RETRYABLE.model_dump(mode="json"))

        assert not await store.save_if(PROJECTION, KEY, DISPATCHED, expected=PENDING)
        assert await store.get(PROJECTION, KEY) == RETRYABLE.model_dump(mode="json")

    async def test_compares_the_record_not_its_spelling(self) -> None:
        """A row written before a field existed still holds the record read from it."""
        store = InMemoryProjectionStore()
        await store.save(PROJECTION, KEY, {"status": "pending"})

        assert await store.save_if(PROJECTION, KEY, DISPATCHED, expected=PENDING)

    async def test_expecting_no_row_writes_only_the_first(self) -> None:
        store = InMemoryProjectionStore()

        assert await store.save_if(PROJECTION, KEY, PENDING, expected=None)
        assert not await store.save_if(PROJECTION, KEY, _Record(status="reset"), expected=None)
        assert await store.get(PROJECTION, KEY) == PENDING.model_dump(mode="json")


class _Conn:
    """One row of one table, and a log of what was asked of it, in order."""

    def __init__(self, row: dict[str, JsonValue] | None) -> None:
        # As asyncpg hands jsonb back without a codec: text.
        self.stored = None if row is None else json.dumps(row)
        self.log: list[str] = []
        self.in_transaction = False

    def transaction(self) -> _Transaction:
        return _Transaction(self)

    async def fetchrow(self, query: str, *args: object) -> dict[str, str] | None:
        del args
        locking = "FOR UPDATE" in query
        self.log.append("lock" if locking else "read")
        assert self.in_transaction or not locking, "the row was locked outside a transaction"
        return None if self.stored is None else {"data": self.stored}

    async def execute(self, query: str, *args: object) -> str:
        assert self.in_transaction, "the row was written outside the transaction"
        data = str(args[1])
        if query.lstrip().startswith("INSERT"):
            assert "DO NOTHING" in query, "an insert that expects no row must not upsert"
            self.log.append("insert")
            if self.stored is not None:
                return "INSERT 0 0"
            self.stored = data
            return "INSERT 0 1"
        self.log.append("update")
        self.stored = data
        return "UPDATE 1"


class _Transaction:
    def __init__(self, conn: _Conn) -> None:
        self._conn = conn

    async def __aenter__(self) -> None:
        self._conn.in_transaction = True

    async def __aexit__(self, *exc: object) -> None:
        self._conn.in_transaction = False


class _Acquire:
    def __init__(self, conn: _Conn) -> None:
        self._conn = conn

    async def __aenter__(self) -> _Conn:
        return self._conn

    async def __aexit__(self, *exc: object) -> None:
        return None


class _Pool:
    def __init__(self, conn: _Conn) -> None:
        self._conn = conn

    def acquire(self) -> _Acquire:
        return _Acquire(self._conn)


def _store(conn: _Conn) -> PostgresProjectionStore:
    store = PostgresProjectionStore()
    store._pool = _Pool(conn)  # type: ignore[assignment]  # a double, not a pool
    store._initialized_tables.add(PROJECTION)
    return store


class TestPostgres:
    async def test_locks_the_row_before_comparing_then_writes(self) -> None:
        conn = _Conn({"status": "pending"})

        assert await _store(conn).save_if(PROJECTION, KEY, DISPATCHED, expected=PENDING)
        assert conn.log == ["lock", "update"]
        assert json.loads(str(conn.stored)) == DISPATCHED.model_dump(mode="json")

    async def test_writes_nothing_over_a_row_that_moved_on(self) -> None:
        conn = _Conn(RETRYABLE.model_dump(mode="json"))

        written = await _store(conn).save_if(PROJECTION, KEY, DISPATCHED, expected=PENDING)

        assert written is False
        assert conn.log == ["lock"], "a stale write reached the table"
        assert json.loads(str(conn.stored)) == RETRYABLE.model_dump(mode="json")

    async def test_expecting_no_row_does_not_overwrite_one(self) -> None:
        conn = _Conn(RETRYABLE.model_dump(mode="json"))

        assert not await _store(conn).save_if(PROJECTION, KEY, PENDING, expected=None)
        assert json.loads(str(conn.stored)) == RETRYABLE.model_dump(mode="json")

    async def test_expecting_no_row_inserts_when_there_is_none(self) -> None:
        conn = _Conn(None)

        assert await _store(conn).save_if(PROJECTION, KEY, PENDING, expected=None)
        assert json.loads(str(conn.stored)) == PENDING.model_dump(mode="json")
