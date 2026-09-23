"""`calculate_many` answers for a whole page in a fixed number of round-trips.

The defect it fixes (#1114) was not a wrong answer, it was a shape: the sessions
list endpoint called the single-session path once per row, so a page cost
~41ms per session against a database that answers the whole page in 2ms.
`limit=200` took 8.3 seconds.

So the load-bearing assertion here is the ROUND-TRIP COUNT, not just the values.
A test that only checked the numbers would pass just as happily against the
per-session loop this replaced.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from syn_domain import tool_call_counts
from syn_domain.contexts.agent_sessions.slices.session_cost.timescale_query import (
    _MIN_TIME_BATCH_QUERY,
    _SESSION_SUMMARY_BATCH_QUERY,
    _TOKEN_USAGE_FALLBACK_BATCH_QUERY,
    MAX_SESSIONS_PER_QUERY,
    TimescaleSessionCostQuery,
)

#: One column value as asyncpg would hand it back. Spelled out rather than left
#: open, so the fixtures state what a row can actually hold - and because the
#: untyped-dict ratchet counts the open shape in test files too.
_Cell = int | str | Decimal | datetime | None
_FakeRow = dict[str, _Cell]
_MODEL = "claude-sonnet-4-5-20250929"

#: Stands in for whatever SQL the tool-call tally issues. Keyed by what the
#: query is FOR rather than by its text: which table holds the tally and how it
#: is read belong to ``tool_call_counts``, and a test that pins the text here
#: would have to be edited every time that module changes its mind (#1322).
_TALLY = "<tool call tally>"


def _summary_row(session_id: str, *, total_input: int | None = 1_000) -> _FakeRow:
    return {
        "session_id": session_id,
        "total_input": total_input,
        "total_output": 500,
        "cache_creation": 0,
        "cache_read": 0,
        "sdk_cost": Decimal("0.25"),
        "duration_ms_val": 4_000,
        "agent_model": _MODEL,
        "workspace_id": "ws-from-summary",
        "completed_at": datetime(2026, 9, 3, 6, 0, tzinfo=UTC),
        "execution_id": "exec-1",
        "phase_id": "verify",
    }


def _token_row(session_id: str) -> _FakeRow:
    return {
        "session_id": session_id,
        "agent_model": _MODEL,
        "total_input": 2_000,
        "total_output": 1_000,
        "cache_creation": 0,
        "cache_read": 0,
        "started_at": datetime(2026, 9, 3, 5, 0, tzinfo=UTC),
        "last_observation": datetime(2026, 9, 3, 5, 30, tzinfo=UTC),
        "workspace_id": "ws-1",
        "observation_count": 9,
        "execution_id": "exec-1",
        "phase_id": "verify",
    }


class _CountingConnection:
    """Serves rows by query text and records every round-trip it was asked for.

    Rows are filtered to the id array the query actually bound, the way the
    database would. That is what makes "every id still has a cost" a real
    assertion once the ids arrive in more than one batch: an implementation
    that fetched only the first batch would go on returning rows for the ids
    it never asked about if the fake ignored the array.
    """

    def __init__(self, rows_by_query: dict[str, list[_FakeRow]]) -> None:
        self._rows_by_query = rows_by_query
        self.calls: list[str] = []
        #: The session-id array bound by each round-trip, in order.
        self.batches: list[list[str]] = []

    async def fetch(self, query: str, *args: object) -> list[_FakeRow]:
        key = _TALLY if tool_call_counts.TABLE in query else query
        self.calls.append(key)
        ids = args[0] if args and isinstance(args[0], list) else None
        if ids is None:
            return self._rows_by_query.get(key, [])
        self.batches.append([str(sid) for sid in ids])
        return [row for row in self._rows_by_query.get(key, []) if row["session_id"] in ids]


class _Acquire:
    def __init__(self, conn: _CountingConnection) -> None:
        self._conn = conn

    async def __aenter__(self) -> _CountingConnection:
        return self._conn

    async def __aexit__(self, *_exc: object) -> bool:
        return False


class _Pool:
    def __init__(self, conn: _CountingConnection) -> None:
        self.conn = conn
        self.acquisitions = 0

    def acquire(self) -> _Acquire:
        self.acquisitions += 1
        return _Acquire(self.conn)


def _query(rows_by_query: dict[str, list[_FakeRow]]) -> tuple[TimescaleSessionCostQuery, _Pool]:
    conn = _CountingConnection(rows_by_query)
    pool = _Pool(conn)
    return TimescaleSessionCostQuery(pool), pool  # type: ignore[arg-type]


@pytest.mark.unit
@pytest.mark.anyio
async def test_cost_for_fifty_sessions_takes_four_round_trips() -> None:
    """The whole point: work is bounded by queries, not by page size."""
    ids = [f"sess-{i}" for i in range(50)]
    q, pool = _query(
        {
            _SESSION_SUMMARY_BATCH_QUERY: [_summary_row(sid) for sid in ids],
            _TALLY: [{"session_id": sid, "cnt": 3} for sid in ids],
            _MIN_TIME_BATCH_QUERY: [
                {"session_id": sid, "started_at": datetime(2026, 9, 3, 5, 0, tzinfo=UTC)}
                for sid in ids
            ],
        }
    )

    results = await q.calculate_many(ids)

    assert len(results) == 50
    # Three queries and one connection for fifty sessions - the fourth, the
    # token_usage fallback, is skipped because every session had a usable
    # summary. The per-session loop this replaced would show 150-200 calls and
    # 50 acquisitions, which is what made a page cost seconds.
    assert pool.conn.calls == [
        _SESSION_SUMMARY_BATCH_QUERY,
        _TALLY,
        _MIN_TIME_BATCH_QUERY,
    ]
    assert pool.acquisitions == 1
    assert results["sess-7"].total_cost_usd == Decimal("0.25")
    assert results["sess-7"].tool_calls == 3


@pytest.mark.unit
@pytest.mark.anyio
async def test_a_summary_without_tokens_falls_back_to_token_usage() -> None:
    """The per-session summary-then-fallback rule, applied across a page.

    `sess-b` has a summary row whose total_input is NULL - not usable - so it
    must be priced from token_usage, while `sess-a` keeps its summary.
    """
    q, _ = _query(
        {
            _SESSION_SUMMARY_BATCH_QUERY: [
                _summary_row("sess-a"),
                _summary_row("sess-b", total_input=None),
            ],
            _TOKEN_USAGE_FALLBACK_BATCH_QUERY: [_token_row("sess-b")],
            _TALLY: [],
            _MIN_TIME_BATCH_QUERY: [],
        }
    )

    results = await q.calculate_many(["sess-a", "sess-b"])

    assert results["sess-a"].total_cost_usd == Decimal("0.25")
    assert results["sess-a"].input_tokens == 1_000
    # From the token_usage row, not the unusable summary.
    assert results["sess-b"].input_tokens == 2_000
    assert results["sess-b"].output_tokens == 1_000
    assert results["sess-b"].workspace_id == "ws-1"


@pytest.mark.unit
@pytest.mark.anyio
async def test_a_session_with_no_data_is_absent_not_zero() -> None:
    """Absent means "no data", which is not the same claim as "cost zero"."""
    q, _ = _query(
        {
            _SESSION_SUMMARY_BATCH_QUERY: [_summary_row("sess-a")],
            _TOKEN_USAGE_FALLBACK_BATCH_QUERY: [],
            _TALLY: [],
            _MIN_TIME_BATCH_QUERY: [],
        }
    )

    results = await q.calculate_many(["sess-a", "sess-missing"])

    assert "sess-a" in results
    assert "sess-missing" not in results


@pytest.mark.unit
@pytest.mark.anyio
async def test_calculate_returns_the_same_answer_as_the_batch_it_delegates_to() -> None:
    """One session is the degenerate case of many, and must stay that way."""
    rows: dict[str, list[_FakeRow]] = {
        _SESSION_SUMMARY_BATCH_QUERY: [_summary_row("sess-a")],
        _TALLY: [{"session_id": "sess-a", "cnt": 2}],
        _MIN_TIME_BATCH_QUERY: [
            {"session_id": "sess-a", "started_at": datetime(2026, 9, 3, 5, 0, tzinfo=UTC)}
        ],
    }
    q_one, _ = _query(rows)
    q_many, _ = _query(rows)

    one = await q_one.calculate("sess-a")
    many = (await q_many.calculate_many(["sess-a"]))["sess-a"]

    assert one is not None
    assert one.total_cost_usd == many.total_cost_usd
    assert one.input_tokens == many.input_tokens
    assert one.tool_calls == many.tool_calls
    assert one.duration_ms == many.duration_ms


@pytest.mark.unit
@pytest.mark.anyio
async def test_no_session_ids_asks_the_database_nothing() -> None:
    q, pool = _query({})

    assert await q.calculate_many([]) == {}
    assert pool.acquisitions == 0


def _page_of(ids: list[str]) -> dict[str, list[_FakeRow]]:
    """Every session priced from its summary, so a page is one round-trip each."""
    return {
        _SESSION_SUMMARY_BATCH_QUERY: [_summary_row(sid) for sid in ids],
        _TALLY: [{"session_id": sid, "cnt": 1} for sid in ids],
        _MIN_TIME_BATCH_QUERY: [
            {"session_id": sid, "started_at": datetime(2026, 9, 3, 5, 0, tzinfo=UTC)} for sid in ids
        ],
    }


@pytest.mark.unit
@pytest.mark.anyio
@pytest.mark.parametrize(
    "count", [MAX_SESSIONS_PER_QUERY - 1, MAX_SESSIONS_PER_QUERY, MAX_SESSIONS_PER_QUERY + 1]
)
async def test_no_round_trip_binds_more_ids_than_the_cap(count: int) -> None:
    """The cap is enforced where the query runs, not where the caller is (#1338).

    ``session_id = ANY($1)`` decompresses a segment per id in that array, so the
    length of the array is the size of the read. The only thing that limited it
    was ``le=200`` on one HTTP parameter, which no other caller passes through.
    """
    ids = [f"sess-{i}" for i in range(count)]
    q, pool = _query(_page_of(ids))

    results = await q.calculate_many(ids)

    assert [len(batch) for batch in pool.conn.batches if len(batch) > MAX_SESSIONS_PER_QUERY] == []
    # Chunking must not lose anyone: the ids past the cap are priced too.
    assert set(results) == set(ids)


@pytest.mark.unit
@pytest.mark.anyio
async def test_a_full_page_is_still_one_batch() -> None:
    """At the cap, behaviour is exactly what it was: four queries, one page.

    The cap restates the HTTP page limit, so the path that motivated #1114 must
    not start paying extra round-trips for the page size it already used.
    """
    ids = [f"sess-{i}" for i in range(MAX_SESSIONS_PER_QUERY)]
    q, pool = _query(_page_of(ids))

    await q.calculate_many(ids)

    assert [len(batch) for batch in pool.conn.batches] == [MAX_SESSIONS_PER_QUERY] * 3
    assert pool.acquisitions == 1


@pytest.mark.unit
@pytest.mark.anyio
async def test_one_id_past_the_cap_becomes_a_second_batch() -> None:
    """One over is two round-trip groups, of the cap and the remainder."""
    ids = [f"sess-{i}" for i in range(MAX_SESSIONS_PER_QUERY + 1)]
    q, pool = _query(_page_of(ids))

    results = await q.calculate_many(ids)

    assert [len(batch) for batch in pool.conn.batches] == [MAX_SESSIONS_PER_QUERY] * 3 + [1] * 3
    assert pool.acquisitions == 2
    assert len(results) == MAX_SESSIONS_PER_QUERY + 1
    assert results[f"sess-{MAX_SESSIONS_PER_QUERY}"].total_cost_usd == Decimal("0.25")
