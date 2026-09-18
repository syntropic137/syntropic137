"""Which ``agent_events`` scans each cost read path still pays for (#1322).

Five places derived their tool-call column by counting
``event_type = 'tool_execution_completed'`` rows in ``agent_events``. That
column is in neither the hypertable's ``compress_segmentby`` (``session_id``)
nor its ``compress_orderby`` (``time``), so the filter is unanswerable from
inside a compressed chunk and every segment of every row on the page gets
decompressed - 60,562 buffer hits, 905ms, for one page of sixteen sessions
over 219,140 rows. /sessions and /executions took 4-30 seconds.

WHAT THIS PROVES, exactly, because the narrow version of it was read as the
broad one: **the tool-count subpath** no longer asks ``agent_events``
anything. It does NOT prove that these endpoints have stopped reading
``agent_events`` - they have not. Token sums, SDK costs, start times, phase
costs and turn counts are still derived from it, several of them filtering on
``event_type`` in exactly the shape described above, just not on
``tool_execution_completed``. #1322 measured and fixed the tool count; #1338
covers the rest.

So rather than assert the absence of one event type and fall silent about
every other, this enumerates. ``_EXPECTED_SCANS`` is the whole remaining set,
written out per endpoint, and the test fails if a read path scans for
something not on the list - an honest acceptance criterion that also stops the
remainder being forgotten, which is what an overclaiming one is for.

Each path is driven TWICE, once per data branch. All five are written as
"prefer the ``session_summary``, fall back to ``token_usage``", and a fixture
that always produces a summary measures only the arm a finished session takes -
leaving the arm every LIVE session takes unmeasured, which is the arm the
dashboard spends its time rendering. ``_Branch`` is the whole of that
distinction; see ``_RecordingConnection``.

The four cost paths live here; the fifth is the ``/executions`` route itself,
covered by ``apps/syn-api/tests/test_executions_list_reads_the_tool_call_tally.py``
where it lives.

The assertion is deliberately about the EVENT TYPE, not the SQL text:
filtering ``agent_events`` on ``tool_execution_completed`` is the only way to
derive the tool count from raw events, so a read path that never mentions it -
bound as an argument or written as a literal - cannot have reintroduced the
scan, however it spells the rest of its query.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import TYPE_CHECKING, NamedTuple

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
from syn_shared.events import (
    SESSION_STARTED,
    SESSION_SUMMARY,
    TOKEN_USAGE,
    TOOL_EXECUTION_COMPLETED,
    VALID_EVENT_TYPES,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Sequence

pytestmark = pytest.mark.unit

_SESSION = "sess-1322"
_EXECUTION = "exec-1322"
_MODEL = "claude-opus-5"
_WHEN = datetime(2026, 9, 17, 10, 0, tzinfo=UTC)
_TOOL_CALLS = 11

#: A read of ``agent_events`` that filters on no event type at all.
_NO_EVENT_TYPE_FILTER = "(no event_type filter)"


class _Branch(Enum):
    """Which of the two shapes of session data the database is holding.

    Every one of these read paths is written as "prefer the summary, fall back
    to ``token_usage``", and the two arms issue different queries and build the
    read model with different code. A double that always answers as though a
    summary exists therefore measures half of each endpoint - and the half it
    skips is the one a live session is served by, because the summary is not
    written until the session ENDS. So each read path is driven twice.
    """

    #: The session has finished and written its ``session_summary``.
    SUMMARISED = "summarised"
    #: The session is still running: ``token_usage`` rows and nothing else.
    IN_PROGRESS = "in-progress"

    def __str__(self) -> str:
        return self.value


class _Case(NamedTuple):
    """One read path in one data branch - the unit everything here is per."""

    endpoint: str
    branch: _Branch

    def __str__(self) -> str:
        return f"{self.endpoint} [{self.branch}]"


def _case(endpoint: str, branch: _Branch) -> _Case:
    return _Case(endpoint, branch)


#: Every ``agent_events`` scan these endpoints still perform, per endpoint and
#: per data branch.
#:
#: This is an inventory, not an allowance: it is here so the remainder is
#: visible and so adding to it takes a deliberate edit. Each entry is a
#: candidate for the same treatment the tool count got - see #1338, which
#: carries this table. The one thing that may never appear in it is
#: ``tool_execution_completed``.
#:
#: The summary query appears in every IN_PROGRESS row too: the fallback is
#: chosen by running that query and finding nothing, so asking is the
#: precondition for falling back, not an alternative to it.
_EXPECTED_SCANS: dict[_Case, frozenset[str]] = {
    _case("GET /costs/sessions (list)", _Branch.SUMMARISED): frozenset(
        {SESSION_SUMMARY, TOKEN_USAGE, SESSION_STARTED}
    ),
    _case("GET /costs/sessions (list)", _Branch.IN_PROGRESS): frozenset(
        {SESSION_SUMMARY, TOKEN_USAGE, SESSION_STARTED}
    ),
    _case("GET /costs/sessions/{id} (detail, via the batch path)", _Branch.SUMMARISED): frozenset(
        {SESSION_SUMMARY, SESSION_STARTED}
    ),
    # The fallback query the summarised row never reaches. Inventoried here
    # rather than merged into the line above, because "this endpoint scans
    # token_usage" is true of one arm and not the other, and a union would say
    # neither.
    _case("GET /costs/sessions/{id} (detail, via the batch path)", _Branch.IN_PROGRESS): frozenset(
        {SESSION_SUMMARY, TOKEN_USAGE, SESSION_STARTED}
    ),
    _case("GET /costs/executions (list)", _Branch.SUMMARISED): frozenset(
        {SESSION_SUMMARY, TOKEN_USAGE}
    ),
    _case("GET /costs/executions (list)", _Branch.IN_PROGRESS): frozenset(
        {SESSION_SUMMARY, TOKEN_USAGE}
    ),
    _case("GET /executions (one page, by id)", _Branch.SUMMARISED): frozenset(
        {SESSION_SUMMARY, TOKEN_USAGE}
    ),
    _case("GET /executions (one page, by id)", _Branch.IN_PROGRESS): frozenset(
        {SESSION_SUMMARY, TOKEN_USAGE}
    ),
    _case("GET /costs/executions/{id} (detail)", _Branch.SUMMARISED): frozenset(
        {SESSION_SUMMARY, _NO_EVENT_TYPE_FILTER}
    ),
    # Two more, both only on this arm: the token_usage fallback itself, and the
    # turn count - which a summarised execution reads off its summary row and an
    # in-progress one gets by counting token_usage rows in agent_events.
    _case("GET /costs/executions/{id} (detail)", _Branch.IN_PROGRESS): frozenset(
        {SESSION_SUMMARY, TOKEN_USAGE, _NO_EVENT_TYPE_FILTER}
    ),
}


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
    """Answers every query with one row, and remembers what it was asked.

    Except the summary query, when the branch is ``IN_PROGRESS``: that one
    comes back empty, which is the whole of what "this session has not
    finished" means to any of these read paths. Nothing else is special-cased,
    so the fallback each of them then takes is its own.
    """

    def __init__(self, branch: _Branch = _Branch.SUMMARISED) -> None:
        self.branch = branch
        self.statements: list[str] = []
        self.args: list[tuple[object, ...]] = []

    def _record(self, query: str, args: tuple[object, ...]) -> None:
        self.statements.append(query)
        self.args.append(args)

    def _has_rows(self, args: tuple[object, ...]) -> bool:
        return self.branch is _Branch.SUMMARISED or SESSION_SUMMARY not in args

    async def execute(self, query: str, *args: object) -> str:
        self._record(query, args)
        return "OK"

    async def fetch(self, query: str, *args: object) -> list[_AnyRow]:
        self._record(query, args)
        return [_AnyRow()] if self._has_rows(args) else []

    async def fetchrow(self, query: str, *args: object) -> _AnyRow | None:
        self._record(query, args)
        return _AnyRow() if self._has_rows(args) else None

    async def fetchval(self, query: str, *args: object) -> object:
        self._record(query, args)
        # ``MIN(time)`` wants a timestamp; the other single-value reads are
        # counts. Dispatching on the query is what lets one double serve both.
        return _WHEN if "MIN(time)" in query else 1

    @property
    def agent_events_scans(self) -> set[str]:
        """Which event types this read path asked ``agent_events`` about.

        Matched against ``VALID_EVENT_TYPES`` rather than against a list kept
        here, so an event type added to the system is one this test already
        knows how to see. A statement that reads ``agent_events`` without
        filtering on a type at all is reported as ``_NO_EVENT_TYPE_FILTER``:
        it is still a scan, and leaving it out would let the widest query of
        the lot be the one nothing records.
        """
        scans: set[str] = set()
        for statement, args in zip(self.statements, self.args, strict=True):
            if "agent_events" not in statement:
                continue
            found = {
                event_type
                for event_type in VALID_EVENT_TYPES
                if f"'{event_type}'" in statement or event_type in {str(arg) for arg in args}
            }
            scans |= found or {_NO_EVENT_TYPE_FILTER}
        return scans

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


def _cases() -> list[tuple[_Case, Callable[[_Pool], Awaitable[object]]]]:
    """Every read path, in both branches - which is what "every read path" means.

    An endpoint driven in one branch is an endpoint half measured, and the
    inventory below is checked against THIS, so a branch that stops being
    exercised cannot go unnoticed either.
    """
    return [
        (_Case(endpoint, branch), read) for endpoint, read in _read_paths() for branch in _Branch
    ]


def _id(value: object) -> str:
    """A test id per case, with no spaces in it, so ``-k`` can select one."""
    return str(value).replace(" ", "-") if isinstance(value, _Case) else ""


def test_the_inventory_covers_every_read_path_in_both_branches() -> None:
    """A case missing from ``_EXPECTED_SCANS`` is an unmeasured case."""
    assert set(_EXPECTED_SCANS) == {case for case, _read in _cases()}


def test_no_read_path_is_permitted_to_count_tool_events() -> None:
    """The one entry the inventory may never gain.

    Half of the criterion, and the half that is a rule rather than a
    measurement: whatever else these endpoints go on reading from
    ``agent_events``, counting ``tool_execution_completed`` is not on the list.
    Paired with the test below - which asserts what each path ACTUALLY scans
    equals its entry here - it says the tool-count scan is gone and cannot be
    put back by editing the inventory.
    """
    for case, expected in _EXPECTED_SCANS.items():
        assert TOOL_EXECUTION_COMPLETED not in expected, (
            f"{case} was granted the scan #1322 removed"
        )


@pytest.mark.parametrize(("case", "read"), _cases(), ids=_id)
async def test_each_read_path_scans_agent_events_for_exactly_what_is_inventoried(
    case: _Case,
    read: Callable[[_Pool], Awaitable[object]],
) -> None:
    """What it actually asks ``agent_events``, against what it is recorded as asking.

    Equality, not containment. A read path that grows a new scan fails here
    even though the new scan is nothing to do with tool calls, and fixing it
    means either removing the query or writing it down - which is the point:
    #1338 inherits a list that cannot quietly get longer.
    """
    conn = _RecordingConnection(case.branch)

    await read(_Pool(conn))

    assert conn.agent_events_scans == _EXPECTED_SCANS[case], (
        f"{case} scans agent_events for {sorted(conn.agent_events_scans)}, "
        f"inventoried as {sorted(_EXPECTED_SCANS[case])}"
    )


@pytest.mark.parametrize(("case", "read"), _cases(), ids=_id)
async def test_every_read_path_reads_the_tally_exactly_once(
    case: _Case,
    read: Callable[[_Pool], Awaitable[object]],
) -> None:
    """Not reading it at all is the other way to pass the test above.

    A read path that dropped the column, or hardcoded zero, would issue no
    offending query either - and would report every session as having used no
    tools, which is the failure this whole change exists to avoid showing.
    """
    conn = _RecordingConnection(case.branch)

    await read(_Pool(conn))

    assert len(conn.tally_reads) == 1, f"{case} read the tally {len(conn.tally_reads)} times"


def _tool_calls_of(result: object) -> Sequence[int]:
    if isinstance(result, list):
        return [int(getattr(item, "tool_calls", -1)) for item in result]
    return [int(getattr(result, "tool_calls", -1))]


@pytest.mark.parametrize(("case", "read"), _cases(), ids=_id)
async def test_the_tallys_number_reaches_the_read_model(
    case: _Case,
    read: Callable[[_Pool], Awaitable[object]],
) -> None:
    """The count has to arrive, not merely be fetched.

    The tally is keyed differently from the rows it accompanies (session vs
    execution), so a correct query whose result is looked up under the wrong
    key returns 0 for everything - silently, because 0 tool calls is an
    ordinary number.

    Per branch, because the lookup is written once per branch: the summary arm
    and the fallback arm build the read model in different functions, and
    getting the key right in one of them is not getting it right.
    """
    conn = _RecordingConnection(case.branch)

    result = await read(_Pool(conn))

    assert _tool_calls_of(result) == [_TOOL_CALLS], f"{case} lost the count"
