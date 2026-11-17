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

``TimescaleRepoCostQuery`` (#2251) has the same shape: a ``session_summary``
read, then a ``token_usage`` fallback for every execution the first read found
no summary for. A session finishing between the two was read as missing by the
first and then priced at zero from turns the second saw after it finished.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, time
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest

from syn_shared.events import SESSION_SUMMARY, TOKEN_USAGE

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


#: The repo every repo-cost test correlates its executions with.
_REPO = "acme/snapshot"
#: What a session's summary reports once it finishes: tokens and vendor cost.
_SUMMARY_TOKENS = 100 + 200 + 0 + 300
_SUMMARY_COST_USD = "0.01"


async def _commit_turn(store, execution_id: str, session_id: str, input_tokens: int) -> None:
    """One ``token_usage`` row for ``session_id``: ``input_tokens`` in, nothing else."""
    await store.insert_one(
        event={
            "event_type": TOKEN_USAGE,
            "session_id": session_id,
            "timestamp": datetime.now(UTC),
            "input_tokens": input_tokens,
            "output_tokens": 0,
            "cache_creation_tokens": 0,
            "cache_read_tokens": 0,
            "model": _MODEL,
        },
        execution_id=execution_id,
    )


async def _commit_summary(store, execution_id: str, session_id: str) -> None:
    """The ``session_summary`` that finishes ``session_id``."""
    await store.insert_one(
        event={
            "event_type": SESSION_SUMMARY,
            "session_id": session_id,
            "timestamp": datetime.now(UTC),
            "total_input_tokens": 100,
            "total_output_tokens": 200,
            "cache_creation_tokens": 0,
            "cache_read_tokens": 300,
            "total_cost_usd": float(_SUMMARY_COST_USD),
            "model": _MODEL,
        },
        execution_id=execution_id,
    )


async def _finish_session(store, execution_id: str, session_id: str) -> None:
    """The session's last turn, then its summary: what a finishing session commits."""
    await _commit_turn(store, execution_id, session_id, 1_000)
    await _commit_summary(store, execution_id, session_id)


async def _correlated(*execution_ids: str):
    from syn_adapters.projection_stores import InMemoryProjectionStore
    from syn_domain.contexts.organization._shared.projection_names import REPO_CORRELATION

    store = InMemoryProjectionStore()
    for execution_id in execution_ids:
        await store.save(
            REPO_CORRELATION,
            f"{execution_id}:{_REPO}",
            {"repo_full_name": _REPO, "execution_id": execution_id},
        )
    return store


def _total(cost) -> tuple[int, Decimal]:
    return (cost.total_tokens, cost.total_cost_usd)


class TestRepoCostOneSnapshot:
    """A repo total is priced from one snapshot, never a mix of two (#2251)."""

    async def test_calculate_for_repo_never_prices_a_finished_session_at_zero(self, event_store):
        from syn_domain.contexts.organization.slices.repo_cost.timescale_query import (
            TimescaleRepoCostQuery,
        )

        execution_id, session_id = str(uuid4()), str(uuid4())
        await _commit_turn(event_store, execution_id, session_id, 10)
        correlations = await _correlated(execution_id)

        # The summary read finds nothing, so the fallback runs: finish the
        # session between them. Read apart, the fallback sees the new turn
        # (1,010 tokens at $0), which neither side of the commit reports.
        pool = _PausingPool(
            event_store.pool,
            lambda conn: _PausingConnection(
                conn, 1, lambda: _finish_session(event_store, execution_id, session_id)
            ),
        )
        cost = await TimescaleRepoCostQuery(pool, correlations).calculate_for_repo(_REPO)  # type: ignore[arg-type]  # a pool double

        assert pool.connection is not None and pool.connection.paused
        after = await TimescaleRepoCostQuery(event_store.pool, correlations).calculate_for_repo(
            _REPO
        )
        before_snapshot = (10, Decimal("0"))
        after_snapshot = (_SUMMARY_TOKENS, Decimal(_SUMMARY_COST_USD))
        assert _total(after) == after_snapshot
        assert _total(cost) in {before_snapshot, after_snapshot}

    async def test_calculate_all_reads_the_fallback_from_the_summary_snapshot(self, event_store):
        from syn_domain.contexts.organization.slices.repo_cost.timescale_query import (
            TimescaleRepoCostQuery,
        )

        finished, running = str(uuid4()), str(uuid4())
        finished_session, running_session = str(uuid4()), str(uuid4())
        await _commit_summary(event_store, finished, finished_session)
        await _commit_turn(event_store, running, running_session, 10)
        correlations = await _correlated(finished, running)

        # The summary read finds ``finished`` only, so the fallback runs for
        # ``running``: finish it between them.
        pool = _PausingPool(
            event_store.pool,
            lambda conn: _PausingConnection(
                conn, 1, lambda: _finish_session(event_store, running, running_session)
            ),
        )
        costs = await TimescaleRepoCostQuery(pool, correlations).calculate_all()  # type: ignore[arg-type]  # a pool double

        assert pool.connection is not None and pool.connection.paused
        after = await TimescaleRepoCostQuery(event_store.pool, correlations).calculate_all()
        summary = (_SUMMARY_TOKENS, Decimal(_SUMMARY_COST_USD))
        # Before: the running session's one turn, unpriced. After: its summary.
        before_snapshot = [(summary[0] + 10, summary[1])]
        after_snapshot = [(summary[0] * 2, summary[1] * 2)]
        assert [_total(c) for c in after] == after_snapshot
        assert [_total(c) for c in costs] in (before_snapshot, after_snapshot)
