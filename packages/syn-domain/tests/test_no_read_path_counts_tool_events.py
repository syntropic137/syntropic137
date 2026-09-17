"""No cost read path asks ``agent_events`` for tool completions (#1322).

Five places derived their tool-call column by counting
``event_type = 'tool_execution_completed'`` rows in ``agent_events``. That
column is in neither the hypertable's ``compress_segmentby`` (``session_id``)
nor its ``compress_orderby`` (``time``), so the filter is unanswerable from
inside a compressed chunk and every segment of every row on the page gets
decompressed - 60,562 buffer hits, 905ms, for one page of sixteen sessions
over 219,140 rows. /sessions and /executions took 4-30 seconds.

This drives each read path against a connection that records its statements
and asserts the count is never derived that way again. Four of the five live
here; the fifth is the ``/executions`` route itself, covered by
``apps/syn-api/tests/test_executions_list_reads_the_tool_call_tally.py``
where it lives.

The assertion is deliberately about the EVENT TYPE, not the SQL text:
filtering ``agent_events`` on ``tool_execution_completed`` is the only way to
derive this count from raw events, so a read path that never mentions it -
bound as an argument or written as a literal - cannot have reintroduced the
scan, however it spells the rest of its query.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest

from syn_domain import tool_call_counts
from syn_domain.contexts.agent_sessions.slices.session_cost.query_service import (
    SessionCostQueryService,
)
from syn_domain.contexts.agent_sessions.slices.session_cost.timescale_query import (
    TimescaleSessionCostQuery,
)
from syn_domain.contexts.orchestration.slices.execution_cost.query_service import (
    ExecutionCostQueryService,
)
from syn_domain.contexts.orchestration.slices.execution_cost.timescale_query import (
    TimescaleExecutionCostQuery,
)
from syn_shared.events import TOOL_EXECUTION_COMPLETED

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Sequence

pytestmark = pytest.mark.unit

_SESSION = "sess-1322"
_EXECUTION = "exec-1322"
_MODEL = "claude-opus-5"
_WHEN = datetime(2026, 9, 17, 10, 0, tzinfo=UTC)
_TOOL_CALLS = 11


def _cell(key: str) -> object:
    """A plausible value for any column any of these queries selects.

    Indifferent to which query asked, on purpose. This test is about which
    statements were issued, and a row that refused a column would end the read
    path early - proving nothing while looking green.
    """
    if key == "session_ids":
        return [_SESSION]
    if key == "session_id":
        return _SESSION
    if key == "execution_id":
        return _EXECUTION
    if key == "phase_id":
        return "implement"
    if key in {"model", "agent_model"}:
        return _MODEL
    if key == "cnt":
        return _TOOL_CALLS
    if key == "sdk_cost":
        return Decimal("1.25")
    if key.endswith(("_at", "_observation", "_time")):
        return _WHEN
    return 1


class _AnyRow:
    def __getitem__(self, key: str) -> object:
        return _cell(key)

    def get(self, key: str, default: object = None) -> object:
        return _cell(key)


class _RecordingConnection:
    """Answers every query with one row, and remembers what it was asked."""

    def __init__(self) -> None:
        self.statements: list[str] = []
        self.args: list[tuple[object, ...]] = []

    def _record(self, query: str, args: tuple[object, ...]) -> None:
        self.statements.append(query)
        self.args.append(args)

    async def execute(self, query: str, *args: object) -> str:
        self._record(query, args)
        return "OK"

    async def fetch(self, query: str, *args: object) -> list[_AnyRow]:
        self._record(query, args)
        return [_AnyRow()]

    async def fetchrow(self, query: str, *args: object) -> _AnyRow:
        self._record(query, args)
        return _AnyRow()

    async def fetchval(self, query: str, *args: object) -> object:
        self._record(query, args)
        # ``MIN(time)`` wants a timestamp; the other single-value reads are
        # counts. Dispatching on the query is what lets one double serve both.
        return _WHEN if "MIN(time)" in query else 1

    @property
    def tool_event_reads(self) -> list[str]:
        """Statements that ask ``agent_events`` about tool completions."""
        return [
            statement
            for statement, args in zip(self.statements, self.args, strict=True)
            if "agent_events" in statement
            and (
                TOOL_EXECUTION_COMPLETED in statement
                or TOOL_EXECUTION_COMPLETED in {str(arg) for arg in args}
            )
        ]

    @property
    def tally_reads(self) -> list[str]:
        return [s for s in self.statements if tool_call_counts.TABLE in s]


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

    def acquire(self) -> _Acquire:
        return _Acquire(self._conn)


def _read_paths() -> list[tuple[str, Callable[[_Pool], Awaitable[object]]]]:
    """Every cost read path that reports a tool-call count, and how to drive it.

    Named by endpoint rather than by class, because what matters is that no
    page a user can open pays for the scan - and the reason four sites drifted
    into the same query is that each was fixed for its own endpoint (#1114,
    #1077) without anyone enumerating the set.
    """
    return [
        (
            "GET /costs/sessions (list)",
            lambda pool: SessionCostQueryService(pool).list_all(),  # type: ignore[arg-type]  # a recording double
        ),
        (
            "GET /costs/sessions/{id} (detail, via the batch path)",
            lambda pool: TimescaleSessionCostQuery(pool).calculate(_SESSION),  # type: ignore[arg-type]
        ),
        (
            "GET /costs/executions (list)",
            lambda pool: ExecutionCostQueryService(pool).list_all(),  # type: ignore[arg-type]
        ),
        (
            "GET /executions (one page, by id)",
            lambda pool: ExecutionCostQueryService(pool).list_for_ids([_EXECUTION]),  # type: ignore[arg-type]
        ),
        (
            "GET /costs/executions/{id} (detail)",
            lambda pool: TimescaleExecutionCostQuery(pool).calculate(_EXECUTION),  # type: ignore[arg-type]
        ),
    ]


@pytest.mark.parametrize(
    ("endpoint", "read"), _read_paths(), ids=lambda v: v if isinstance(v, str) else ""
)
async def test_no_read_path_counts_tool_events_in_agent_events(
    endpoint: str,
    read: Callable[[_Pool], Awaitable[object]],
) -> None:
    conn = _RecordingConnection()

    await read(_Pool(conn))

    assert not conn.tool_event_reads, (
        f"{endpoint} still counts tool_execution_completed rows in agent_events: "
        f"{conn.tool_event_reads}"
    )


@pytest.mark.parametrize(
    ("endpoint", "read"), _read_paths(), ids=lambda v: v if isinstance(v, str) else ""
)
async def test_every_read_path_reads_the_tally_exactly_once(
    endpoint: str,
    read: Callable[[_Pool], Awaitable[object]],
) -> None:
    """Not reading it at all is the other way to pass the test above.

    A read path that dropped the column, or hardcoded zero, would issue no
    offending query either - and would report every session as having used no
    tools, which is the failure this whole change exists to avoid showing.
    """
    conn = _RecordingConnection()

    await read(_Pool(conn))

    assert len(conn.tally_reads) == 1, f"{endpoint} read the tally {len(conn.tally_reads)} times"


def _tool_calls_of(result: object) -> Sequence[int]:
    if isinstance(result, list):
        return [int(getattr(item, "tool_calls", -1)) for item in result]
    return [int(getattr(result, "tool_calls", -1))]


@pytest.mark.parametrize(
    ("endpoint", "read"), _read_paths(), ids=lambda v: v if isinstance(v, str) else ""
)
async def test_the_tallys_number_reaches_the_read_model(
    endpoint: str,
    read: Callable[[_Pool], Awaitable[object]],
) -> None:
    """The count has to arrive, not merely be fetched.

    The tally is keyed differently from the rows it accompanies (session vs
    execution), so a correct query whose result is looked up under the wrong
    key returns 0 for everything - silently, because 0 tool calls is an
    ordinary number.
    """
    conn = _RecordingConnection()

    result = await read(_Pool(conn))

    assert _tool_calls_of(result) == [_TOOL_CALLS], f"{endpoint} lost the count"
