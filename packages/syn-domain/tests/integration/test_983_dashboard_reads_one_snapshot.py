"""A dashboard response is read from ONE snapshot, never from several (#983).

``CanonicalUsageQueryService.totals()`` and ``TimescaleHeatmapQuery.query()``
each build one response from several statements on one connection. At READ
COMMITTED every statement takes its own snapshot, so a session committed
between two of them shows up in one number and not the other: its tokens
counted, its session not, or the reverse.

Each test pauses the read between two of its statements, commits a new
session with usage from a second connection, lets the read finish, and
asserts the response is entirely from before the commit or entirely from
after it. On the old code the tokens include the new session and the session
count does not.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, time
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest

from syn_shared.events import SESSION_SUMMARY

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable

    import asyncpg

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

_MODEL = "haiku"
_MIDDAY = time(12, 0, tzinfo=UTC)
#: Every session seeded here reports these tokens, so N sessions are N x this.
_TOKENS_PER_SESSION = 100 + 200 + 0 + 300


class _PausingConnection:
    """A pooled connection that runs ``between`` after its ``pause_after``-th read.

    Everything else is the real connection, so the read under test runs its
    real statements, in its real transaction, against the real database.
    """

    def __init__(
        self,
        conn: asyncpg.pool.PoolConnectionProxy,
        pause_after: int,
        between: Callable[[], Awaitable[None]],
    ) -> None:
        self._conn = conn
        self._pause_after = pause_after
        self._between = between
        self._reads = 0
        self.paused = False

    def __getattr__(self, name: str) -> object:
        return getattr(self._conn, name)

    async def _after_read(self) -> None:
        self._reads += 1
        if self._reads == self._pause_after:
            self.paused = True
            await self._between()

    async def fetch(self, query: str, *args: object) -> list[asyncpg.Record]:
        rows = await self._conn.fetch(query, *args)
        await self._after_read()
        return rows

    async def fetchrow(self, query: str, *args: object) -> asyncpg.Record | None:
        row = await self._conn.fetchrow(query, *args)
        await self._after_read()
        return row


class _PausingPool:
    """Hands out one :class:`_PausingConnection`; the store's own pool is the writer."""

    def __init__(
        self, pool: asyncpg.Pool, connection_factory: Callable[[object], _PausingConnection]
    ) -> None:
        self._pool = pool
        self._factory = connection_factory
        self.connection: _PausingConnection | None = None

    @asynccontextmanager
    async def acquire(self) -> AsyncIterator[_PausingConnection]:
        async with self._pool.acquire() as conn:
            self.connection = self._factory(conn)
            yield self.connection


@pytest.fixture
def utc_day() -> date:
    """The one UTC day seeded and queried, read once (see #1001)."""
    return datetime.now(UTC).date()


@pytest.fixture
async def event_store(test_infrastructure):
    from syn_adapters.events import AgentEventStore

    store = AgentEventStore(test_infrastructure.timescaledb_url)
    await store.initialize()
    yield store
    await store.close()


async def _commit_session(store, day: date, execution_id: str) -> None:
    """One finished session with usage, committed through the production writer."""
    await store.insert_one(
        event={
            "event_type": SESSION_SUMMARY,
            "session_id": str(uuid4()),
            "timestamp": datetime.combine(day, _MIDDAY),
            "total_input_tokens": 100,
            "total_output_tokens": 200,
            "cache_creation_tokens": 0,
            "cache_read_tokens": 300,
            "total_cost_usd": 0.01,
            "model": _MODEL,
        },
        execution_id=execution_id,
    )


def _snapshot(sessions: int) -> tuple[int, int]:
    """What a consistent read of ``sessions`` seeded sessions reports."""
    return (sessions * _TOKENS_PER_SESSION, sessions)


class TestOneResponseOneSnapshot:
    async def test_totals_never_count_tokens_without_their_session(self, event_store, utc_day):
        from syn_domain.contexts.agent_sessions import CostCalculator
        from syn_domain.contexts.agent_sessions.slices.canonical_totals import (
            CanonicalUsageQueryService,
        )

        execution_id = str(uuid4())
        await _commit_session(event_store, utc_day, execution_id)
        await _commit_session(event_store, utc_day, execution_id)

        # totals() reads tokens, then sessions: commit a third session between.
        pool = _PausingPool(
            event_store.pool,
            lambda conn: _PausingConnection(
                conn, 1, lambda: _commit_session(event_store, utc_day, execution_id)
            ),
        )
        card = await CanonicalUsageQueryService(pool, CostCalculator()).totals(  # type: ignore[arg-type]  # a pool double
            execution_ids={execution_id}
        )

        assert pool.connection is not None and pool.connection.paused
        # The third session really committed, so a consistent read is either side of it.
        after = await CanonicalUsageQueryService(event_store.pool, CostCalculator()).totals(
            execution_ids={execution_id}
        )
        assert (after.total_tokens, after.sessions) == _snapshot(3)
        assert (card.total_tokens, card.sessions) in {_snapshot(2), _snapshot(3)}

    async def test_heatmap_sessions_and_usage_buckets_agree(self, event_store, utc_day):
        from syn_domain.contexts.organization.slices.contribution_heatmap.TimescaleHeatmapQuery import (
            TimescaleHeatmapQuery,
        )

        execution_id = str(uuid4())
        await _commit_session(event_store, utc_day, execution_id)
        await _commit_session(event_store, utc_day, execution_id)

        # query() reads executions, commits, sessions, usage: commit a third
        # session after sessions and before usage.
        pool = _PausingPool(
            event_store.pool,
            lambda conn: _PausingConnection(
                conn, 3, lambda: _commit_session(event_store, utc_day, execution_id)
            ),
        )
        buckets = await TimescaleHeatmapQuery(pool).query(  # type: ignore[arg-type]  # a pool double
            start=utc_day, end=utc_day, execution_ids={execution_id}
        )

        def read(day_buckets) -> tuple[int, int]:
            return (
                int(sum(b.breakdown["tokens"] for b in day_buckets)),
                int(sum(b.breakdown["sessions"] for b in day_buckets)),
            )

        assert pool.connection is not None and pool.connection.paused
        after = await TimescaleHeatmapQuery(event_store.pool).query(
            start=utc_day, end=utc_day, execution_ids={execution_id}
        )
        assert read(after) == _snapshot(3)
        assert read(buckets) in {_snapshot(2), _snapshot(3)}
