"""Domain read services must ask for an id the way agent_events holds it (#1241).

``AgentEvent`` sanitises a correlation id when the event is built, so every
row in ``agent_events`` is keyed by the sanitised spelling. A read service
that binds the raw one matches no row - and each of these services turns "no
rows" into a legitimate-looking answer: no cost, an empty heatmap, zero
totals. Nothing raises.

So each test here is a round trip: the table holds a row under the spelling
the writer produced (taken FROM the writer, not typed out beside it), the
reader is called with the spelling an outside caller holds, and the
assertion is that the reader found it.

The double knows exactly one thing - which id its rows are filed under. It
returns them when a query binds that id and returns nothing when it does not,
which is all Postgres does here and all this bug is.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

pytestmark = pytest.mark.unit

NUL = chr(0)
LONE_SURROGATE = chr(0xDEAD)

#: The id as a harness hands it to us, and the only spelling Postgres can hold.
RAW_ID = "exec-" + NUL + "abc" + LONE_SURROGATE + "def"
STORED_ID = "exec-abcdef"

_MODEL = "claude-sonnet-4-5-20250929"
_DAY = date(2026, 9, 17)
_WHEN = datetime(2026, 9, 17, 12, 0, tzinfo=UTC)


def _stored_spelling() -> str:
    """What the WRITER makes of ``RAW_ID`` - asked, not assumed."""
    from syn_adapters.events.models import AgentEvent

    event = AgentEvent(event_type="session_summary", execution_id=RAW_ID, session_id=RAW_ID)
    assert event.execution_id == event.session_id
    assert event.execution_id is not None
    return event.execution_id


def test_the_writer_stores_a_different_spelling() -> None:
    """Guards every assertion below: if these were equal, nothing is tested."""
    assert _stored_spelling() == STORED_ID
    assert RAW_ID != STORED_ID


#: One column value, as asyncpg would hand it back.
type _Cell = int | str | Decimal | datetime | date | list[str] | None


class _Row:
    """A row with both access styles asyncpg's Record supports."""

    def __init__(self, cells: dict[str, _Cell]) -> None:
        self._cells = cells

    def __getitem__(self, key: str) -> _Cell:
        return self._cells[key]

    def get(self, key: str, default: _Cell = None) -> _Cell:
        return self._cells.get(key, default)

    def first(self) -> _Cell:
        """The first column, which is what ``fetchval`` returns."""
        return next(iter(self._cells.values()), None)


class _AgentEvents:
    """Rows filed under one id, served only to queries that ask for that id."""

    def __init__(self, stored_id: str, rows_by_query: dict[str, list[_Row]]) -> None:
        self._stored_id = stored_id
        self._rows_by_query = rows_by_query
        self.missed: list[str] = []

    def _asked_for_stored_id(self, args: tuple[object, ...]) -> bool:
        for arg in args:
            if arg == self._stored_id:
                return True
            if isinstance(arg, (list, tuple, set)) and self._stored_id in arg:
                return True
        return False

    def _rows(self, query: str, args: tuple[object, ...]) -> list[_Row]:
        if not self._asked_for_stored_id(args):
            self.missed.append(query)
            return []
        for text, rows in self._rows_by_query.items():
            if text in query:
                return rows
        return []

    async def fetch(self, query: str, *args: object) -> list[_Row]:
        return self._rows(query, args)

    async def fetchrow(self, query: str, *args: object) -> _Row | None:
        rows = self._rows(query, args)
        return rows[0] if rows else None

    async def fetchval(self, query: str, *args: object) -> _Cell:
        row = await self.fetchrow(query, *args)
        return None if row is None else row.first()


class _Acquire:
    def __init__(self, conn: _AgentEvents) -> None:
        self._conn = conn

    async def __aenter__(self) -> _AgentEvents:
        return self._conn

    async def __aexit__(self, *_exc: object) -> bool:
        return False


class _Pool:
    def __init__(self, conn: _AgentEvents) -> None:
        self.conn = conn

    def acquire(self) -> _Acquire:
        return _Acquire(self.conn)


def _pool(rows_by_query: dict[str, list[_Row]]) -> _Pool:
    return _Pool(_AgentEvents(STORED_ID, rows_by_query))


# --- Session cost -------------------------------------------------------------


def _session_summary_row() -> _Row:
    return _Row(
        {
            "session_id": STORED_ID,
            "total_input": 1_000,
            "total_output": 500,
            "cache_creation": 0,
            "cache_read": 0,
            "sdk_cost": Decimal("0.25"),
            "duration_ms_val": 4_000,
            "agent_model": _MODEL,
            "completed_at": _WHEN,
            "execution_id": STORED_ID,
            "phase_id": "verify",
        }
    )


async def test_session_cost_reads_back_a_session_written_with_a_nul_id() -> None:
    from syn_domain.contexts.agent_sessions.slices.session_cost.timescale_query import (
        _SESSION_SUMMARY_BATCH_QUERY,
        TimescaleSessionCostQuery,
    )

    query = TimescaleSessionCostQuery(
        _pool({_SESSION_SUMMARY_BATCH_QUERY: [_session_summary_row()]})
    )

    cost = await query.calculate(RAW_ID)

    assert cost is not None
    assert cost.total_cost_usd == Decimal("0.25")


async def test_session_cost_batch_keys_results_by_the_stored_id() -> None:
    """A caller looks the result up by id, so the KEY has to be the stored one."""
    from syn_domain.contexts.agent_sessions.slices.session_cost.timescale_query import (
        _SESSION_SUMMARY_BATCH_QUERY,
        TimescaleSessionCostQuery,
    )

    query = TimescaleSessionCostQuery(
        _pool({_SESSION_SUMMARY_BATCH_QUERY: [_session_summary_row()]})
    )

    results = await query.calculate_many([RAW_ID])

    assert STORED_ID in results


# --- Execution cost -----------------------------------------------------------


def _token_usage_group_row(*, execution_id: str | None = None) -> _Row:
    cells: dict[str, _Cell] = {
        "model": _MODEL,
        "total_input": 1_000,
        "total_output": 500,
        "cache_creation": 0,
        "cache_read": 0,
        "session_count": 1,
        "session_ids": [STORED_ID],
        "started_at": _WHEN,
        "last_observation": _WHEN,
        "observation_count": 4,
    }
    if execution_id is not None:
        cells["execution_id"] = execution_id
    return _Row(cells)


async def test_execution_cost_reads_back_an_execution_written_with_a_nul_id() -> None:
    from syn_domain.contexts.orchestration.slices.execution_cost.timescale_query import (
        _TOKEN_USAGE_FALLBACK_QUERY,
        TimescaleExecutionCostQuery,
    )

    query = TimescaleExecutionCostQuery(
        _pool({_TOKEN_USAGE_FALLBACK_QUERY: [_token_usage_group_row()]})
    )

    cost = await query.calculate(RAW_ID)

    assert cost is not None
    assert cost.input_tokens == 1_000


async def test_execution_cost_batch_reads_back_ids_written_with_a_nul() -> None:
    from syn_domain.contexts.orchestration.slices.execution_cost.query_service import (
        _BY_IDS_FROM_TOKEN_USAGE_QUERY,
        ExecutionCostQueryService,
    )

    service = ExecutionCostQueryService(
        _pool({_BY_IDS_FROM_TOKEN_USAGE_QUERY: [_token_usage_group_row(execution_id=STORED_ID)]})
    )

    costs = await service.list_for_ids([RAW_ID])

    assert [c.execution_id for c in costs] == [STORED_ID]


# --- Canonical totals ---------------------------------------------------------


async def test_canonical_totals_counts_sessions_of_a_nul_bearing_execution() -> None:
    from syn_domain.contexts.agent_sessions import CostCalculator
    from syn_domain.contexts.agent_sessions.slices.canonical_totals.query_service import (
        CanonicalUsageQueryService,
    )

    service = CanonicalUsageQueryService(
        _pool({"COUNT(DISTINCT session_id) AS sessions": [_Row({"sessions": 3})]}),
        CostCalculator(),
    )

    totals = await service.totals({RAW_ID})

    assert totals.sessions == 3


# --- Contribution heatmap -----------------------------------------------------


async def test_heatmap_scoped_to_a_nul_bearing_execution_is_not_empty() -> None:
    from syn_domain.contexts.organization.slices.contribution_heatmap.TimescaleHeatmapQuery import (
        _SESSIONS_QUERY,
        TimescaleHeatmapQuery,
    )

    # The fragment that belongs to the sessions template alone - the three
    # heatmap templates share a long CTE prologue, so a prefix would feed
    # session rows to the token query.
    assert "FROM session_start" in _SESSIONS_QUERY
    query = TimescaleHeatmapQuery(
        _pool({"FROM session_start\nGROUP BY day": [_Row({"day": _DAY, "sessions": 2})]})
    )

    buckets = await query.query(_DAY, _DAY, execution_ids={RAW_ID})

    assert len(buckets) == 1
    assert buckets[0].breakdown["sessions"] == 2
