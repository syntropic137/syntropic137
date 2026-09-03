"""``calculate_many`` answers for a whole page in a fixed number of queries (#1077).

``/api/v1/sessions`` enriched its list by calling ``calculate`` once per
session. ``calculate`` spends up to four round trips and holds a pool
connection for each, so a 20-session page cost up to 80 sequential queries -
paid again on every dashboard poll. #1087 fixed the identical defect on
``/api/v1/executions`` with a batched query; this is the session-side twin.

What these tests pin, and why each matters:

* the query count does not grow with the number of sessions - the property
  that distinguishes a batch from a loop, and from ``asyncio.gather``, which
  would make the round trips concurrent without making them fewer;
* one session's numbers land on that session and no other - a loop could not
  mis-key its result, a batch can;
* ``calculate`` and ``calculate_many`` agree, which they do structurally
  because there is only one implementation, so the test guards the structure
  rather than re-deriving the arithmetic;
* one unpriceable session does not blank the rest of the page - a property the
  per-session loop got for free from having a query boundary per session.

Timing is deliberately never asserted. A wall-clock threshold passes on an idle
machine even with the loop restored, and fails on a loaded one with the fix in
place, so it tests the machine rather than the code.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from syn_domain.contexts.agent_sessions.slices.session_cost.query_service import (
    SessionCostQueryService,
)
from syn_domain.contexts.agent_sessions.slices.session_cost.timescale_query import (
    _COUNTS_BY_SESSION_QUERY,
    _MIN_TIMES_BY_SESSION_QUERY,
    _SESSION_SUMMARIES_QUERY,
    _TOKEN_USAGE_FALLBACK_BY_SESSIONS_QUERY,
    TimescaleSessionCostQuery,
)

_FakeRow = Mapping[str, object]

_SONNET = "claude-sonnet-4-20250514"
_OPUS = "claude-opus-4-20250514"


def _summary_row(session_id: str, sdk_cost: str | None, model: str = _SONNET) -> _FakeRow:
    """A ``session_summary`` row as ``_SESSION_SUMMARIES_QUERY`` projects it."""
    return {
        "session_id": session_id,
        "total_input": 1_000,
        "total_output": 2_000,
        "cache_creation": 0,
        "cache_read": 0,
        "sdk_cost": sdk_cost,
        "duration_ms_val": 36_000,
        "agent_model": model,
        "completed_at": datetime(2026, 9, 3, 12, 0, tzinfo=UTC),
        "execution_id": "exec-1",
        "phase_id": "phase-1",
    }


def _token_usage_row(session_id: str, model: str | None = _SONNET) -> _FakeRow:
    """A ``token_usage`` row as ``_TOKEN_USAGE_FALLBACK_BY_SESSIONS_QUERY`` projects it."""
    return {
        "session_id": session_id,
        "agent_model": model,
        "total_input": 1_000,
        "total_output": 2_000,
        "cache_creation": 0,
        "cache_read": 0,
        "started_at": datetime(2026, 9, 3, 11, 0, tzinfo=UTC),
        "last_observation": datetime(2026, 9, 3, 11, 30, tzinfo=UTC),
        "workspace_id": "ws-1",
        "observation_count": 7,
        "execution_id": "exec-1",
        "phase_id": "phase-1",
    }


class _CountingConnection:
    """Dispatches ``fetch`` by query text and counts every call.

    Dispatching by text rather than returning one canned list keeps each row
    shape tied to the SQL that produces it - otherwise a test stays green while
    the code reads the wrong query for the wrong purpose. The counter is what
    makes "one round trip per query, not per session" assertable without timing.
    """

    def __init__(
        self,
        summary_rows: list[_FakeRow],
        token_rows: list[_FakeRow],
        tool_rows: list[_FakeRow],
        started_rows: list[_FakeRow],
    ) -> None:
        self._by_query = {
            _SESSION_SUMMARIES_QUERY: summary_rows,
            _TOKEN_USAGE_FALLBACK_BY_SESSIONS_QUERY: token_rows,
            _COUNTS_BY_SESSION_QUERY: tool_rows,
            _MIN_TIMES_BY_SESSION_QUERY: started_rows,
        }
        self.fetch_calls: list[str] = []

    async def fetch(self, query: str, *_args: object) -> list[_FakeRow]:
        self.fetch_calls.append(query)
        return self._by_query[query]


class _StubAcquire:
    def __init__(self, conn: _CountingConnection) -> None:
        self._conn = conn

    async def __aenter__(self) -> _CountingConnection:
        return self._conn

    async def __aexit__(self, *_exc: object) -> bool:
        return False


class _CountingPool:
    """Counts ``acquire`` too: a batch must hold one connection, not one per id."""

    def __init__(self, conn: _CountingConnection) -> None:
        self.conn = conn
        self.acquire_count = 0

    def acquire(self) -> _StubAcquire:
        self.acquire_count += 1
        return _StubAcquire(self.conn)


def _pool_for(session_ids: list[str], *, summarized: bool = True) -> _CountingPool:
    """A pool serving one priced session per id, via summary or token_usage rows."""
    rows = [
        _summary_row(sid, sdk_cost=f"{i + 1}.50") if summarized else _token_usage_row(sid)
        for i, sid in enumerate(session_ids)
    ]
    return _CountingPool(
        _CountingConnection(
            summary_rows=rows if summarized else [],
            token_rows=[] if summarized else rows,
            tool_rows=[{"session_id": sid, "cnt": 3} for sid in session_ids],
            started_rows=[
                {"session_id": sid, "started_at": datetime(2026, 9, 3, 11, 0, tzinfo=UTC)}
                for sid in session_ids
            ],
        )
    )


@pytest.mark.unit
class TestQueryCountDoesNotGrowWithSessionCount:
    """The defining property of the fix: fixed round trips, whatever the page size."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("session_count", [1, 5, 20])
    async def test_one_fetch_per_query_shape_not_per_session(self, session_count: int) -> None:
        ids = [f"sess-{i}" for i in range(session_count)]
        pool = _pool_for(ids)
        conn = pool.conn

        costs = await TimescaleSessionCostQuery(pool).calculate_many(ids)  # pyright: ignore[reportArgumentType]

        assert len(costs) == session_count
        # Summary, tool counts, start times. The token_usage fallback is skipped
        # because every session here has a usable summary.
        assert len(conn.fetch_calls) == 3, (
            f"{session_count} sessions cost {len(conn.fetch_calls)} round trips: {conn.fetch_calls}"
        )
        assert pool.acquire_count == 1

    @pytest.mark.asyncio
    async def test_unsummarised_sessions_add_the_fallback_query_once(self) -> None:
        """The fallback is one more query for the batch, not one more per session."""
        ids = [f"sess-{i}" for i in range(20)]
        pool = _pool_for(ids, summarized=False)
        conn = pool.conn

        costs = await TimescaleSessionCostQuery(pool).calculate_many(ids)  # pyright: ignore[reportArgumentType]

        assert len(costs) == 20
        assert len(conn.fetch_calls) == 4, conn.fetch_calls

    @pytest.mark.asyncio
    async def test_service_list_for_ids_is_the_same_batched_call(self) -> None:
        """The seam the API route actually uses, not just the layer beneath it."""
        ids = [f"sess-{i}" for i in range(20)]
        pool = _pool_for(ids)
        conn = pool.conn

        costs = await SessionCostQueryService(pool).list_for_ids(ids)  # pyright: ignore[reportArgumentType]

        assert set(costs) == set(ids)
        assert len(conn.fetch_calls) == 3, conn.fetch_calls
        assert pool.acquire_count == 1


@pytest.mark.unit
class TestBatchingDoesNotChangeTheAnswer:
    @pytest.mark.asyncio
    async def test_each_session_keeps_its_own_cost(self) -> None:
        """Distinct per-session costs, so a mis-keyed batch cannot pass."""
        ids = ["sess-0", "sess-1", "sess-2"]
        pool = _pool_for(ids)

        costs = await TimescaleSessionCostQuery(pool).calculate_many(ids)  # pyright: ignore[reportArgumentType]

        assert costs["sess-0"].total_cost_usd == Decimal("1.50")
        assert costs["sess-1"].total_cost_usd == Decimal("2.50")
        assert costs["sess-2"].total_cost_usd == Decimal("3.50")

    @pytest.mark.asyncio
    async def test_batched_result_equals_the_single_session_result(self) -> None:
        """``calculate`` and ``calculate_many`` must agree field for field.

        They cannot disagree by construction - ``calculate`` delegates here -
        and that is what this pins: if someone reintroduces a separate
        single-session query path, the two answers become free to drift and
        this fails.
        """
        ids = ["sess-0", "sess-1", "sess-2"]

        batched = await TimescaleSessionCostQuery(_pool_for(ids)).calculate_many(ids)  # pyright: ignore[reportArgumentType]
        one_at_a_time = {
            sid: await TimescaleSessionCostQuery(_pool_for(ids)).calculate(sid) for sid in ids
        }

        assert batched == one_at_a_time

    @pytest.mark.asyncio
    async def test_a_session_with_no_observations_is_absent_not_zeroed(self) -> None:
        """Absent means "we know nothing"; a zeroed record would read as "free"."""
        pool = _pool_for(["sess-known"])

        costs = await TimescaleSessionCostQuery(pool).calculate_many(  # pyright: ignore[reportArgumentType]
            ["sess-known", "sess-silent"]
        )

        assert set(costs) == {"sess-known"}

    @pytest.mark.asyncio
    async def test_a_summary_missing_token_totals_falls_back_to_token_usage(self) -> None:
        """The summary/token_usage choice must survive batching.

        A summary row with no ``total_input`` is not usable, and the
        single-session path has always fallen through to token_usage for it.
        Treating "has a summary row" as "is summarised" would zero the session
        instead.
        """
        unusable = dict(_summary_row("sess-partial", sdk_cost=None))
        unusable["total_input"] = None
        unusable["total_output"] = None
        pool = _CountingPool(
            _CountingConnection(
                summary_rows=[unusable],
                token_rows=[_token_usage_row("sess-partial", _OPUS)],
                tool_rows=[],
                started_rows=[],
            )
        )

        costs = await TimescaleSessionCostQuery(pool).calculate_many(["sess-partial"])  # pyright: ignore[reportArgumentType]

        assert costs["sess-partial"].agent_model == _OPUS
        assert costs["sess-partial"].input_tokens == 1_000


@pytest.mark.unit
class TestOneBadSessionDoesNotBlankThePage:
    @pytest.mark.asyncio
    async def test_an_unpriceable_session_is_skipped_and_the_rest_survive(self) -> None:
        """The per-session error boundary the loop provided must survive batching.

        ``sdk_cost`` here is a value ``Decimal`` cannot parse, which is the
        realistic shape of the failure: one session's JSON payload is malformed
        while the other nineteen are fine. Before batching each session had its
        own query and so its own boundary. Without an explicit boundary the one
        bad row would take the whole page's enrichment down with it - and the
        dashboard polls this endpoint, so it would take it down repeatedly.
        """
        good_a = _summary_row("sess-good-a", sdk_cost="1.50")
        good_b = _summary_row("sess-good-b", sdk_cost="2.50")
        poisoned = _summary_row("sess-bad", sdk_cost="not-a-number")
        pool = _CountingPool(
            _CountingConnection(
                summary_rows=[good_a, poisoned, good_b],
                token_rows=[],
                tool_rows=[],
                started_rows=[],
            )
        )

        costs = await TimescaleSessionCostQuery(pool).calculate_many(  # pyright: ignore[reportArgumentType]
            ["sess-good-a", "sess-bad", "sess-good-b"]
        )

        assert set(costs) == {"sess-good-a", "sess-good-b"}
        assert costs["sess-good-a"].total_cost_usd == Decimal("1.50")
        assert costs["sess-good-b"].total_cost_usd == Decimal("2.50")

    @pytest.mark.asyncio
    async def test_a_transport_failure_still_propagates(self) -> None:
        """Per-session containment must not swallow "the database is gone".

        A pool that cannot be acquired is not a partial answer to salvage; the
        caller has to be able to tell "no cost data" from "no database", and
        the per-session loop could not have salvaged anything here either.
        """

        class _BrokenPool:
            def acquire(self) -> _StubAcquire:
                raise ConnectionError("pool exhausted")

        with pytest.raises(ConnectionError):
            await TimescaleSessionCostQuery(_BrokenPool()).calculate_many(["sess-0"])  # pyright: ignore[reportArgumentType]
