"""``GET /executions`` reads tool calls from the tally, once (#1322).

The route used to read the tally itself AND have the cost read read it again
for the same ids, then throw the second answer away. Now the cost read is the
only reader, and the route takes the count from it. So this pins, for one list
page, every round trip the enrichment makes - a regression that puts the
second read back, or any other statement, changes the list and fails here.

The fixture's execution has tool calls and NOTHING else: no summary, no
``token_usage`` row. That is a live execution whose harness reports usage at
the end of a turn, and it is the case that would read 0 tool calls if the count
only travelled with a cost row. It could not show 11 without the tally reaching
the summary through the cost read.

The sibling proof for the domain read paths is
``packages/syn-domain/tests/test_cost_read_path_agent_events_scans.py``.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from datetime import date
from typing import TYPE_CHECKING

import pytest

from syn_domain import tool_call_counts
from syn_domain.contexts.orchestration.domain.read_models.workflow_execution_summary import (
    WorkflowExecutionSummary,
)
from syn_domain.contexts.orchestration.slices.execution_cost.projection import (
    ExecutionCostProjection,
)
from syn_domain.pagination import Page
from syn_shared.events import SESSION_SUMMARY, TOKEN_USAGE, TOOL_EXECUTION_COMPLETED

if TYPE_CHECKING:
    from collections.abc import Collection

    from syn_api.routes.executions.models import ExecutionSummaryResponse

pytestmark = pytest.mark.unit

_EXECUTION = "exec-1322"
_DAY = date(2026, 10, 7)

#: What one list page's enrichment sends, in order, and nothing else. The BEGIN
#: carries the read-only snapshot (``agent_event_span.custom_plans``), so it is
#: not followed by a ``SET TRANSACTION``.
_BEGIN = "BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY"
_PLAN = "plan setting"
_SPAN = "day span"
_SUMMARY = "session_summary read"
_TOKENS = "token_usage read"
_TALLY = "tool-call tally"
_EXPECTED_ROUND_TRIPS = [_BEGIN, _PLAN, _SPAN, _SUMMARY, _TOKENS, _TALLY]


@dataclass(frozen=True)
class _Row:
    """A row read by column name the way asyncpg's ``Record`` is."""

    execution_id: str = _EXECUTION
    cnt: int = 11
    first_day: date = _DAY
    last_day: date = _DAY

    def __getitem__(self, column: str) -> object:
        if column not in {f.name for f in fields(self)}:
            raise KeyError(column)
        return getattr(self, column)


def _kind(statement: str, args: tuple[object, ...]) -> str:
    if statement == _BEGIN:
        return _BEGIN
    if "plan_cache_mode" in statement:
        return _PLAN
    if "agent_event_day_rollup" in statement:
        return _SPAN
    if tool_call_counts.TABLE in statement:
        return _TALLY
    # The two agent_events reads differ by the event type they bind.
    if "agent_events" in statement and SESSION_SUMMARY in args:
        return _SUMMARY
    if "agent_events" in statement and TOKEN_USAGE in args:
        return _TOKENS
    return f"unaccounted: {statement}"


class _RecordingConnection:
    """Answers the span and the tally, and nothing else: an execution with tool calls only."""

    def __init__(self) -> None:
        self.statements: list[str] = []
        self.args: list[tuple[object, ...]] = []

    def _record(self, query: str, args: tuple[object, ...]) -> None:
        self.statements.append(query)
        self.args.append(args)

    def transaction(self, *, isolation: str, readonly: bool) -> _Transaction:
        assert (isolation, readonly) == ("repeatable_read", True)
        return _Transaction(self)

    async def execute(self, query: str, *args: object) -> str:
        self._record(query, args)
        return "SET"

    async def fetch(self, query: str, *args: object) -> list[_Row]:
        self._record(query, args)
        if "agent_event_day_rollup" in query or tool_call_counts.TABLE in query:
            return [_Row()]
        return []

    @property
    def kinds(self) -> list[str]:
        return [_kind(s, args) for s, args in zip(self.statements, self.args, strict=True)]


class _Transaction:
    def __init__(self, conn: _RecordingConnection) -> None:
        self._conn = conn

    async def __aenter__(self) -> None:
        # The BEGIN is a round trip like any other.
        self._conn._record(_BEGIN, ())

    async def __aexit__(self, *_exc: object) -> bool:
        return False


class _Acquire:
    def __init__(self, conn: _RecordingConnection) -> None:
        self._conn = conn

    async def __aenter__(self) -> _RecordingConnection:
        return self._conn

    async def __aexit__(self, *_exc: object) -> bool:
        return False


class _Pool:
    def __init__(self, conn: _RecordingConnection) -> None:
        self._conn = conn
        self.acquisitions = 0

    def acquire(self) -> _Acquire:
        self.acquisitions += 1
        return _Acquire(self._conn)


#: What the domain summary already knows about the execution's tokens, from
#: phases it completed before this turn. None of it is in Lane 2.
_DOMAIN_INPUT = 60
_DOMAIN_OUTPUT = 30
_DOMAIN_CACHE_CREATION = 7
_DOMAIN_CACHE_READ = 3
_DOMAIN_TOTAL = 100


def _summary() -> WorkflowExecutionSummary:
    return WorkflowExecutionSummary(
        workflow_execution_id=_EXECUTION,
        workflow_id="wf-1",
        workflow_name="Workflow",
        status="running",
        started_at="2026-10-07T08:00:00+00:00",
        completed_at=None,
        completed_phases=1,
        total_phases=2,
        total_tokens=_DOMAIN_TOTAL,
        total_input_tokens=_DOMAIN_INPUT,
        total_output_tokens=_DOMAIN_OUTPUT,
        total_cache_creation_tokens=_DOMAIN_CACHE_CREATION,
        total_cache_read_tokens=_DOMAIN_CACHE_READ,
    )


class _ExecutionList:
    async def page(
        self,
        *,
        statuses: Collection[str] | None,
        started_after: object,
        started_before: object,
        search: str | None,
        tags: object,
        eval_id: str | None,
        offset: int,
        limit: int | None,
    ) -> Page[WorkflowExecutionSummary]:
        return Page(rows=[_summary()], total=1, status_counts={"running": 1})


class _Manager:
    def __init__(self, pool: _Pool) -> None:
        self.workflow_execution_list = _ExecutionList()
        # The real cost read, over the recording pool. Its store is never
        # touched when it has a pool: it reads TimescaleDB directly.
        self.execution_cost = ExecutionCostProjection(store=None, pool=pool)  # type: ignore[arg-type]  # a recording double


class _EventStore:
    def __init__(self, pool: _Pool) -> None:
        self.pool = pool


async def _one_page(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[_RecordingConnection, _Pool, int]:
    conn, pool, response = await _one_response(monkeypatch)
    return conn, pool, response.tool_call_count


async def _one_response(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[_RecordingConnection, _Pool, ExecutionSummaryResponse]:
    """One list page, as the endpoint composes its single row."""
    from syn_api import _wiring
    from syn_api.routes.executions.queries import (
        _build_execution_summary_response,
        _load_execution_list_data,
        _to_execution_summary,
    )

    conn = _RecordingConnection()
    pool = _Pool(conn)
    # The route's own way to the database is the same recorder, so a read it
    # issued beside the cost read - the duplicate this replaced - is counted.
    store = _EventStore(pool)
    monkeypatch.setattr(_wiring, "get_event_store_instance", lambda: store)
    page, enrichment = await _load_execution_list_data(
        _Manager(pool),  # type: ignore[arg-type]  # a recording double
        None,
        None,
        20,
        0,
    )
    [response] = [
        _build_execution_summary_response(
            _to_execution_summary(s, enrichment), enrichment.get(s.workflow_execution_id)
        )
        for s in page.rows
    ]
    return conn, pool, response


async def test_one_list_page_makes_exactly_the_pinned_round_trips(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn, pool, _count = await _one_page(monkeypatch)

    assert conn.kinds == _EXPECTED_ROUND_TRIPS
    assert pool.acquisitions == 1, "the list page took more than one connection"


async def test_the_tally_is_read_once_and_its_count_reaches_the_summary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn, _pool, count = await _one_page(monkeypatch)

    assert conn.kinds.count(_TALLY) == 1
    assert count == 11


async def test_no_statement_counts_tool_events(monkeypatch: pytest.MonkeyPatch) -> None:
    """The scan #1322 removed is not put back by the single read."""
    conn, _pool, _count = await _one_page(monkeypatch)

    for statement, args in zip(conn.statements, conn.args, strict=True):
        assert TOOL_EXECUTION_COMPLETED not in statement
        assert TOOL_EXECUTION_COMPLETED not in {str(arg) for arg in args}


async def test_a_tally_without_tokens_leaves_the_domain_token_totals_alone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tool calls are not a token observation, so they cannot report zero tokens.

    Lane 2 has no summary and no ``token_usage`` row for this execution, only
    its tally. The tokens the domain summary holds are the only ones anybody
    measured, and carrying the tally must not replace them with zeros.
    """
    _conn, _pool, response = await _one_response(monkeypatch)

    assert response.tool_call_count == 11
    assert response.total_input_tokens == _DOMAIN_INPUT
    assert response.total_output_tokens == _DOMAIN_OUTPUT
    assert response.total_cache_creation_tokens == _DOMAIN_CACHE_CREATION
    assert response.total_cache_read_tokens == _DOMAIN_CACHE_READ
    assert response.total_tokens == _DOMAIN_TOTAL
