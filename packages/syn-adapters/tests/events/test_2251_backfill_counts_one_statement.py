"""The backfill's pending and abandoned counts come from ONE statement (#2251).

Two ``count(*)`` statements at READ COMMITTED take two snapshots, so a session
abandoned between them was counted in neither or in both.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, cast

import pytest

from syn_adapters.events.shipped_backfill import (
    AttributionLookup,
    BackfillLimits,
    BackfillReport,
    _Clock,
    _retry_pending,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    import asyncpg

    from syn_adapters.events.shipped_ledger import PostgresShippedLedger

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]


class _Connection:
    """Serves the count as one row; any other read is a second statement and fails."""

    def __init__(self, pending: int, abandoned: int) -> None:
        self._row = {"pending": pending, "abandoned": abandoned}
        self.reads: list[str] = []
        self.writes: list[str] = []

    async def fetchrow(self, query: str, *_args: object) -> object:
        self.reads.append(query)
        return self._row

    async def execute(self, query: str, *_args: object) -> str:
        self.writes.append(query)
        return "UPDATE 1"


class _Pool:
    def __init__(self, conn: _Connection) -> None:
        self._conn = conn

    @asynccontextmanager
    async def acquire(self) -> AsyncIterator[_Connection]:
        yield self._conn


async def _no_sleep(_seconds: float) -> None:
    return None


async def _run(conn: _Connection) -> BackfillReport:
    limits = BackfillLimits(rounds_per_run=0)
    report = BackfillReport()
    await _retry_pending(
        cast("asyncpg.Pool", _Pool(conn)),
        cast("PostgresShippedLedger", None),
        cast("AttributionLookup", None),
        limits,
        _Clock(limits, _no_sleep),
        report,
        _no_sleep,
    )
    return report


async def test_both_counts_come_from_one_statement() -> None:
    conn = _Connection(pending=3, abandoned=2)

    report = await _run(conn)

    assert len(conn.reads) == 1
    assert "FILTER (WHERE NOT abandoned)" in conn.reads[0]
    assert "FILTER (WHERE abandoned)" in conn.reads[0]
    assert (report.pending, report.abandoned, report.done) == (3, 2, False)
    assert conn.writes == []


async def test_nothing_pending_marks_the_backfill_done() -> None:
    conn = _Connection(pending=0, abandoned=4)

    report = await _run(conn)

    assert (report.pending, report.abandoned, report.done) == (0, 4, True)
    assert conn.writes == ["UPDATE shipped_ledger_meta SET backfill_done_at = now()"]
