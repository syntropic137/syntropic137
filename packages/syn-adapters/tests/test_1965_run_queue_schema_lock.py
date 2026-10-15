"""The Run Queue schema is applied one process at a time and ledgered (#1965).

Unit half: the order of statements ``ensure_ready`` sends, on a recording
connection. The real-Postgres half (two processes, double apply on pre-pool
data) is ``test_1965_run_queue_schema_postgres.py``, marked integration.
"""

from __future__ import annotations

import hashlib
import re
import struct
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

import pytest

from syn_adapters import advisory_locks
from syn_adapters.advisory_locks import (
    ROLLUP_SCHEMA_LOCK_KEY,
    ROLLUP_STARTUP_LOCK_KEY,
    RUN_QUEUE_SCHEMA_LOCK_KEY,
    SESSION_UNLOCK_SQL,
    USAGE_ROLLUP_SCHEMA_LOCK_KEY,
)
from syn_adapters.execution_runs import PostgresExecutionRunQueue
from syn_adapters.execution_runs.postgres import SCHEMA_STEPS, schema_steps

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Sequence

    from syn_adapters.session_inventory.database import Row

# CI runs `pytest -m unit`; an unmarked module collects zero tests (#1065).
pytestmark = pytest.mark.unit

_BEGIN = "BEGIN"
_COMMIT = "COMMIT"
_ROLLBACK = "ROLLBACK"
# Written out rather than imported: an oracle that is the production constant
# moves with it, so `pg_advisory_lock` in its place would still pass (#1965).
TRY_SESSION_LOCK_SQL = "SELECT pg_try_advisory_lock($1)"
# A blocked waiter holds a snapshot that CREATE INDEX CONCURRENTLY waits on (#1906).
_BLOCKING_LOCK = re.compile(r"\bpg_advisory(_xact)?_lock(_shared)?\s*\(")


def _refuse_blocking_lock(query: str) -> None:
    if _BLOCKING_LOCK.search(query):
        raise AssertionError(f"a startup lock must never block: {query!r}")


class _Transaction:
    def __init__(self, conn: _RecordingConnection) -> None:
        self._conn = conn

    async def __aenter__(self) -> object:
        self._conn.calls.append((_BEGIN, ()))
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        self._conn.calls.append((_ROLLBACK if exc_type else _COMMIT, ()))


class _RecordingConnection:
    """Records every statement; the lock is refused ``refusals`` times first."""

    def __init__(self, *, refusals: int = 0, fail_on: str | None = None) -> None:
        self.calls: list[tuple[str, tuple[object, ...]]] = []
        self._refusals = refusals
        self._fail_on = fail_on

    async def execute(self, query: str, *args: object) -> object:
        self.calls.append((query, args))
        _refuse_blocking_lock(query)
        if self._fail_on is not None and query == self._fail_on:
            raise RuntimeError("step failed")
        return "OK"

    async def fetchval(self, query: str, *args: object) -> str | None:
        self.calls.append((query, args))
        _refuse_blocking_lock(query)
        if query == TRY_SESSION_LOCK_SQL:
            if self._refusals:
                self._refusals -= 1
                return None
            return "t"
        return None

    async def fetch(self, query: str, *args: object) -> Sequence[Row]:
        raise AssertionError(f"ensure_ready does not read rows: {query}")

    def transaction(self) -> _Transaction:
        return _Transaction(self)


class _OneConnectionPool:
    def __init__(self, conn: _RecordingConnection) -> None:
        self._conn = conn

    @asynccontextmanager
    async def acquire(self) -> AsyncIterator[_RecordingConnection]:
        yield self._conn


def _queue(conn: _RecordingConnection) -> PostgresExecutionRunQueue:
    return PostgresExecutionRunQueue(_OneConnectionPool(conn))  # type: ignore[arg-type]


def _statements(conn: _RecordingConnection) -> list[str]:
    return [query for query, _ in conn.calls]


async def test_every_schema_statement_runs_inside_the_run_queue_session_lock() -> None:
    conn = _RecordingConnection()
    await _queue(conn).ensure_ready()

    statements = _statements(conn)
    assert conn.calls[0] == (TRY_SESSION_LOCK_SQL, (RUN_QUEUE_SCHEMA_LOCK_KEY,))
    assert conn.calls[-1] == (SESSION_UNLOCK_SQL, (RUN_QUEUE_SCHEMA_LOCK_KEY,))
    # The lock is taken outside any transaction: a waiter holds no snapshot.
    assert _BEGIN not in statements[: statements.index(TRY_SESSION_LOCK_SQL) + 1]
    for step in SCHEMA_STEPS:
        assert step.sql in statements[1:-1]


async def test_a_refused_lock_is_retried_with_no_transaction_open_between_attempts() -> None:
    conn = _RecordingConnection(refusals=3)
    await _queue(conn).ensure_ready()

    statements = _statements(conn)
    assert statements[:4] == [TRY_SESSION_LOCK_SQL] * 4
    assert statements.count(TRY_SESSION_LOCK_SQL) == 4
    # Nothing but lock attempts happens before the lock is won.
    assert SCHEMA_STEPS[0].sql not in statements[:4]


async def test_each_step_commits_with_its_ledger_row_in_file_order() -> None:
    conn = _RecordingConnection()
    await _queue(conn).ensure_ready()

    recorded = [
        args[0]
        for query, args in conn.calls
        if query.startswith("INSERT INTO execution_run_queue_schema_steps")
    ]
    assert recorded == [step.name for step in SCHEMA_STEPS]
    statements = _statements(conn)
    for step in SCHEMA_STEPS:
        at = statements.index(step.sql)
        assert statements[at - 1] == _BEGIN
        assert statements[at + 1].startswith("INSERT INTO execution_run_queue_schema_steps")
        assert statements[at + 2] == _COMMIT


async def test_the_lock_is_released_when_a_step_fails() -> None:
    failing = SCHEMA_STEPS[2].sql
    conn = _RecordingConnection(fail_on=failing)
    with pytest.raises(RuntimeError, match="step failed"):
        await _queue(conn).ensure_ready()

    assert conn.calls[-1] == (SESSION_UNLOCK_SQL, (RUN_QUEUE_SCHEMA_LOCK_KEY,))
    statements = _statements(conn)
    # The failed step rolled back without its ledger row; no later step ran.
    assert statements[statements.index(failing) + 1] == _ROLLBACK
    assert SCHEMA_STEPS[3].sql not in statements


def test_schema_sql_is_fully_divided_into_named_steps() -> None:
    names = [step.name for step in SCHEMA_STEPS]
    assert names[0] == "executor_hosts"
    assert "execution_budget_drop_backend" in names
    assert all(step.sql.strip() for step in SCHEMA_STEPS)


def test_sql_before_the_first_step_is_refused() -> None:
    with pytest.raises(ValueError, match="before its first"):
        schema_steps("CREATE TABLE t (x INT);\n-- step: a\nSELECT 1;\n")


def test_a_step_named_twice_is_refused() -> None:
    with pytest.raises(ValueError, match="twice"):
        schema_steps("-- step: a\nSELECT 1;\n-- step: a\nSELECT 2;\n")


def _legacy_key(name: bytes) -> int:
    return struct.unpack(">q", hashlib.blake2b(name, digest_size=8).digest())[0]


def test_moving_the_rollup_keys_kept_their_values() -> None:
    # A rolling deploy runs old and new images together; a changed key would
    # let both hold "the" rollup lock at once.
    assert _legacy_key(b"agent_event_day_rollup:schema") == ROLLUP_SCHEMA_LOCK_KEY
    assert _legacy_key(b"agent_event_day_rollup:startup") == ROLLUP_STARTUP_LOCK_KEY
    assert _legacy_key(b"agent_usage_rollup:schema") == USAGE_ROLLUP_SCHEMA_LOCK_KEY


def test_every_startup_lock_key_is_distinct() -> None:
    keys = [
        value
        for name, value in vars(advisory_locks).items()
        if name.endswith("_LOCK_KEY") and isinstance(value, int)
    ]
    assert RUN_QUEUE_SCHEMA_LOCK_KEY in keys
    assert len(keys) == len(set(keys)) == 4
