"""#1041: a finalized session's cost must arrive at the API with real values.

The DTO hop was fixed first, and every test of it passed while the endpoint
still served defaults - because the PRODUCERS never populated the fields. A
mapper test cannot see that: it starts from a hand-built ``SessionCost``, which
is a substitute for the producer, not the producer.

So these tests start at the rows and end at ``SessionCostResponse``:

    agent_events rows -> SessionCostQueryService -> SessionCost
        -> session_cost_to_data -> SessionCostData
        -> _session_cost_to_api -> SessionCostResponse

``_ProjectingConnection`` is what makes that honest. A stub that hands back a
dict keyed by column name returns ``workspace_id`` whether or not the SQL ever
selected it, so it would have passed against the pre-fix queries. This one
projects a canonical event row through the query's OWN select list, so a column
the SQL does not name is invisible to the builder - the same way it is in
Postgres. Delete ``workspace_id`` from any of the three queries and these tests
fail.
"""

from __future__ import annotations

import dataclasses
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest

from syn_api.routes.costs import _session_cost_to_api, session_cost_to_data
from syn_domain.contexts.agent_sessions.domain.read_models.session_cost import CostField
from syn_domain.contexts.agent_sessions.slices.session_cost.query_service import (
    _LIST_ALL_FROM_SUMMARY_QUERY,
    _LIST_ALL_FROM_TOKEN_USAGE_QUERY,
    _STARTED_AT_BY_SESSION_QUERY,
    _TOOL_COUNT_BY_SESSION_QUERY,
    SessionCostQueryService,
)
from syn_domain.contexts.agent_sessions.slices.session_cost.timescale_query import (
    _COUNT_BATCH_QUERY,
    _MIN_TIME_BATCH_QUERY,
    _SESSION_SUMMARY_BATCH_QUERY,
    _TOKEN_USAGE_FALLBACK_BATCH_QUERY,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from syn_api.routes.costs import SessionCostResponse

pytestmark = pytest.mark.unit

_MODEL = "claude-opus-5"
_WORKSPACE = "ws-1041-finalized"

#: No read path over ``agent_events`` can derive these: a ``tool_completed``
#: row carries no tokens, a ``token_usage`` row carries no tool, and nothing
#: prices compute. Their zeroes are labelled, not measured.
_NEVER_MEASURED = sorted(f.value for f in CostField if f is not CostField.TURNS)

#: ``turns`` is the per-path case: ``num_turns`` exists only on a
#: ``session_summary`` event, so a finalized session measures it and a live one
#: cannot. The two lists differing by exactly this is the point.
_UNMEASURED_WHEN_FINALIZED = _NEVER_MEASURED
_UNMEASURED_WHEN_LIVE = sorted([*_NEVER_MEASURED, CostField.TURNS.value])

_DISTINCT_ON = re.compile(r"^\s*DISTINCT\s+ON\s*\([^)]*\)", re.IGNORECASE)


def _selected_aliases(query: str) -> list[str]:
    """The output column names a query actually projects.

    Reads the text between SELECT and FROM, splitting only on commas outside
    parentheses so ``COALESCE(a, 0) as b`` stays one item, and taking each
    item's ``as <alias>`` or, failing that, its bare column name.
    """
    body = query[query.upper().index("SELECT") + len("SELECT") : query.upper().index("FROM")]
    body = _DISTINCT_ON.sub("", body)

    items: list[str] = []
    depth = 0
    current = ""
    for char in body:
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        if char == "," and depth == 0:
            items.append(current)
            current = ""
        else:
            current += char
    items.append(current)

    aliases: list[str] = []
    for item in items:
        tokens = item.split()
        if len(tokens) >= 2 and tokens[-2].lower() == "as":
            aliases.append(tokens[-1])
        elif len(tokens) == 1 and tokens[0]:
            aliases.append(tokens[0])
    return aliases


@dataclass(frozen=True)
class _SummaryEvent:
    """A finalized ``session_summary`` row, holding every column any query names.

    Named typed fields rather than a column -> value mapping. The mapping is
    what lets a double answer for a column nobody selected, and it is also what
    this repo's typing rules forbid.
    """

    session_id: str
    total_input: int
    total_output: int
    cache_creation: int
    cache_read: int
    sdk_cost: Decimal
    duration_ms_val: int
    agent_model: str
    num_turns: int
    tool_count: int
    workspace_id: str
    completed_at: datetime
    execution_id: str
    phase_id: str


@dataclass(frozen=True)
class _TokenEvent:
    """A live session's aggregated ``token_usage`` row - no summary exists yet."""

    session_id: str
    agent_model: str
    total_input: int
    total_output: int
    cache_creation: int
    cache_read: int
    started_at: datetime
    last_observation: datetime
    workspace_id: str
    observation_count: int
    execution_id: str
    phase_id: str


@dataclass(frozen=True)
class _ToolCountRow:
    session_id: str
    cnt: int


@dataclass(frozen=True)
class _StartedAtRow:
    session_id: str
    started_at: datetime


_EventRow = _SummaryEvent | _TokenEvent | _ToolCountRow | _StartedAtRow


@dataclass(frozen=True)
class _ProjectedRow:
    """The columns one query selected, read the way asyncpg's ``Record`` is read.

    Raising ``KeyError`` for a column the query never named is the whole point:
    it is what Postgres does, and a double that answered anyway is what let
    #1041 pass its tests while the endpoint served defaults.
    """

    source: _EventRow
    columns: frozenset[str]

    def __getitem__(self, column: str) -> object:
        if column not in self.columns:
            raise KeyError(column)
        return getattr(self.source, column)

    def get(self, column: str, default: object = None) -> object:
        if column not in self.columns:
            return default
        return getattr(self.source, column)


def _columns_of(row: _EventRow) -> frozenset[str]:
    return frozenset(f.name for f in dataclasses.fields(row))


class _ProjectingConnection:
    """Serves each query only the columns that query selects.

    The point of the indirection: a test double that answers with every column
    regardless of the SQL cannot fail when a SELECT drops one, which is the
    exact defect #1041 is about.
    """

    def __init__(self, rows_by_query: Mapping[str, Sequence[_EventRow]]) -> None:
        self._rows_by_query = rows_by_query

    async def fetch(self, query: str, *_args: object) -> list[_ProjectedRow]:
        aliases = frozenset(_selected_aliases(query))
        return [
            _ProjectedRow(source=row, columns=aliases & _columns_of(row))
            for row in self._rows_by_query.get(query, [])
        ]


class _Acquire:
    def __init__(self, conn: _ProjectingConnection) -> None:
        self._conn = conn

    async def __aenter__(self) -> _ProjectingConnection:
        return self._conn

    async def __aexit__(self, *_exc: object) -> bool:
        return False


class _Pool:
    def __init__(self, conn: _ProjectingConnection) -> None:
        self._conn = conn

    def acquire(self) -> _Acquire:
        return _Acquire(self._conn)


def _service(
    rows_by_query: Mapping[str, Sequence[_EventRow]],
) -> SessionCostQueryService:
    return SessionCostQueryService(pool=_Pool(_ProjectingConnection(rows_by_query)))  # type: ignore[arg-type]


#: Every column any of the queries could name, as one finalized session_summary
#: event. ``_ProjectingConnection`` narrows it per query.
_SUMMARY_EVENT = _SummaryEvent(
    session_id="sess-1041",
    total_input=16_229,
    total_output=1_535,
    cache_creation=4_096,
    cache_read=144_640,
    sdk_cost=Decimal("1.234567"),
    duration_ms_val=36_000,
    agent_model=_MODEL,
    num_turns=7,
    tool_count=10,
    workspace_id=_WORKSPACE,
    completed_at=datetime(2026, 9, 17, 10, 30, tzinfo=UTC),
    execution_id="exec-1041",
    phase_id="implement",
)

_TOKEN_EVENT = _TokenEvent(
    session_id="sess-live",
    agent_model=_MODEL,
    total_input=2_000,
    total_output=1_000,
    cache_creation=0,
    cache_read=0,
    started_at=datetime(2026, 9, 17, 10, 0, tzinfo=UTC),
    last_observation=datetime(2026, 9, 17, 10, 5, tzinfo=UTC),
    workspace_id="ws-1041-live",
    observation_count=9,
    execution_id="exec-1041",
    phase_id="implement",
)


async def _finalized_response() -> SessionCostResponse:
    """The detail endpoint's answer for a finalized session, producer-first."""
    service = _service(
        {
            _SESSION_SUMMARY_BATCH_QUERY: [_SUMMARY_EVENT],
            _COUNT_BATCH_QUERY: [_ToolCountRow(session_id="sess-1041", cnt=10)],
            _MIN_TIME_BATCH_QUERY: [
                _StartedAtRow(
                    session_id="sess-1041",
                    started_at=datetime(2026, 9, 17, 10, 0, tzinfo=UTC),
                )
            ],
            _TOKEN_USAGE_FALLBACK_BATCH_QUERY: [],
        }
    )
    cost = await service.get("sess-1041")
    assert cost is not None
    return _session_cost_to_api(session_cost_to_data(cost))


async def _listed_responses() -> dict[str, SessionCostResponse]:
    """The list endpoint's answers, keyed by session id."""
    service = _service(
        {
            _LIST_ALL_FROM_SUMMARY_QUERY: [_SUMMARY_EVENT],
            _LIST_ALL_FROM_TOKEN_USAGE_QUERY: [_TOKEN_EVENT],
            _TOOL_COUNT_BY_SESSION_QUERY: [_ToolCountRow(session_id="sess-1041", cnt=10)],
            _STARTED_AT_BY_SESSION_QUERY: [
                _StartedAtRow(
                    session_id="sess-1041",
                    started_at=datetime(2026, 9, 17, 10, 0, tzinfo=UTC),
                )
            ],
        }
    )
    listed = await service.list_all()
    responses = {c.session_id: _session_cost_to_api(session_cost_to_data(c)) for c in listed}
    assert set(responses) == {"sess-1041", "sess-live"}
    return responses


@pytest.mark.anyio
class TestFinalizedSessionDetail:
    """``GET /costs/sessions/{id}`` for a session that has a session_summary."""

    async def test_workspace_id_reaches_the_response(self) -> None:
        # The path a finalized session actually takes is the summary query, not
        # the token_usage fallback - so the fallback's workspace_id, which was
        # already selected before #1041, cannot be what makes this pass.
        assert (await _finalized_response()).workspace_id == _WORKSPACE

    async def test_the_measured_fields_are_real_values(self) -> None:
        response = await _finalized_response()
        assert response.total_cost_usd == Decimal("1.234567")
        assert response.cache_read_tokens == 144_640

    async def test_unmeasured_fields_names_the_underivable_fields(self) -> None:
        assert (await _finalized_response()).unmeasured_fields == _UNMEASURED_WHEN_FINALIZED

    async def test_each_unmeasured_field_is_at_its_default(self) -> None:
        # The pairing is the contract: the zero is only honest because the name
        # ships beside it. A future producer that fills one of these must drop
        # it from unmeasured_fields, and this test is what notices if it does not.
        response = await _finalized_response()
        assert response.compute_cost_usd == Decimal("0")
        assert response.tokens_by_tool == {}
        assert response.cost_by_tool_tokens == {}
        assert set(response.unmeasured_fields) == set(_UNMEASURED_WHEN_FINALIZED)

    async def test_a_session_with_a_summary_reports_itself_finalized(self) -> None:
        # This endpoint reported every finished session as still running: the
        # detail producer never set the flag its list-path twin already set.
        assert (await _finalized_response()).is_finalized is True

    async def test_turns_is_measured_and_not_a_default(self) -> None:
        response = await _finalized_response()
        assert response.turns == 7
        assert CostField.TURNS.value not in response.unmeasured_fields


@pytest.mark.anyio
class TestSessionList:
    """``GET /costs/sessions`` - both list producers, in one call."""

    async def test_summary_path_carries_workspace_id(self) -> None:
        assert (await _listed_responses())["sess-1041"].workspace_id == _WORKSPACE

    async def test_token_usage_path_carries_workspace_id(self) -> None:
        assert (await _listed_responses())["sess-live"].workspace_id == "ws-1041-live"

    async def test_unmeasured_fields_differs_by_what_the_path_can_see(self) -> None:
        # The finalized session measured its turns; the live one has no
        # session_summary to read them from and says so instead of claiming 0.
        responses = await _listed_responses()
        assert responses["sess-1041"].unmeasured_fields == _UNMEASURED_WHEN_FINALIZED
        assert responses["sess-live"].unmeasured_fields == _UNMEASURED_WHEN_LIVE
        assert responses["sess-live"].turns == 0


class TestTheDoubleIsBoundToTheSQL:
    """Without this, the tests above could pass against the pre-#1041 queries."""

    def test_a_query_that_omits_a_column_cannot_serve_it(self) -> None:
        narrowed = _SESSION_SUMMARY_BATCH_QUERY.replace(
            "    data->>'workspace_id' as workspace_id,\n", ""
        )
        assert narrowed != _SESSION_SUMMARY_BATCH_QUERY, "the select line moved; update this test"
        assert "workspace_id" not in _selected_aliases(narrowed)

    def test_every_query_projects_the_columns_its_builder_reads(self) -> None:
        for query in (
            _SESSION_SUMMARY_BATCH_QUERY,
            _TOKEN_USAGE_FALLBACK_BATCH_QUERY,
            _LIST_ALL_FROM_SUMMARY_QUERY,
            _LIST_ALL_FROM_TOKEN_USAGE_QUERY,
        ):
            assert "workspace_id" in _selected_aliases(query)

    def test_both_summary_queries_project_num_turns(self) -> None:
        # Only a session_summary event carries num_turns, so both queries over
        # it must select it - the batch one did not, and the detail endpoint
        # reported 0 turns for every finished session.
        assert "num_turns" in _selected_aliases(_SESSION_SUMMARY_BATCH_QUERY)
        assert "num_turns" in _selected_aliases(_LIST_ALL_FROM_SUMMARY_QUERY)
