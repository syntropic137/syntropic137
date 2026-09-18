"""Which ``agent_events`` scans each cost read path still pays for (#1338).

Every cost query pairs an id with an ``event_type``. ``event_type`` is in
neither the hypertable's ``compress_segmentby`` (``session_id``) nor its
``compress_orderby`` (``time``), so inside a compressed chunk it cannot be
answered from any index - the batch is decompressed and filtered row by row.
#1338 shipped the two composite indexes that serve the uncompressed chunks
(see ``002_agent_events.sql``), which bounds the cost for recent data and
changes nothing for compressed data.

What decides whether that residual cost is survivable is the ID each query
leads on, so this file records that alongside the event type:

  * ``session_id`` IS the segmentby column. A compressed chunk discards whole
    segments before decompressing any of them, so the work stays proportional
    to the sessions on the page. Safe at scale, and the reason the session-cost
    paths are left reading raw events.
  * ``execution_id`` is neither segmentby nor orderby. Nothing narrows the
    chunk, so every segment in range is decompressed to find one execution's
    rows. NOT safe at scale; an index cannot fix it and only a read model can.

So this is an inventory, not a prohibition: it pins the exact remaining set so
it cannot grow unnoticed, and marks which members are accepted and which are
outstanding debt. A new scan of either kind fails the test and has to be
argued for here.

The assertion is on the event type BOUND AS AN ARGUMENT, not on SQL text - a
read path cannot derive an aggregate from raw events without naming the type
it wants, however it spells the rest of the query. ``_NO_EVENT_TYPE_FILTER``
stands for a query that filters on an id alone, which is strictly worse: it
reads every type there is.

Each path is driven TWICE, once per data branch. All of them are "prefer the
session_summary, fall back to token_usage", and a fixture that always produces
a summary leaves the arm every LIVE session takes unmeasured - which is the arm
the dashboard spends its time rendering.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, NamedTuple

import pytest

from syn_domain.contexts.agent_sessions.slices.session_cost.timescale_query import (
    TimescaleSessionCostQuery,
)
from syn_domain.contexts.orchestration.slices.execution_cost.timescale_query import (
    TimescaleExecutionCostQuery,
)
from syn_shared.events import (
    SESSION_STARTED,
    SESSION_SUMMARY,
    TOKEN_USAGE,
    TOOL_EXECUTION_COMPLETED,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

pytestmark = pytest.mark.unit

_SESSION = "sess-1338"
_EXECUTION = "exec-1338"

#: A query that filters ``agent_events`` on an id and NOTHING else, so it reads
#: every event type for that id. Worse than an event_type filter, not better.
_NO_EVENT_TYPE_FILTER = "<no event_type filter>"


class _Scan(NamedTuple):
    """One ``agent_events`` read: the event type asked for, and the id led on."""

    event_type: str
    keyed_by: str


# Which id each query leads on, decided by the parameter the path binds. Both
# spellings of the session key lead on session_id; ANY($1) over a page of ids
# is still a segmentby restriction.
_SESSION_KEY = "session_id"
_EXECUTION_KEY = "execution_id"


class _RecordingConnection:
    """Records every ``agent_events`` read, and answers from one data branch.

    ``has_summary`` is the whole of the branch distinction: with it, the paths
    take their authoritative ``session_summary`` arm; without it, every one of
    them falls through to ``token_usage``, which is what a still-running
    session does.
    """

    def __init__(self, *, has_summary: bool) -> None:
        self._has_summary = has_summary
        self.scans: list[_Scan] = []

    def _record(self, sql: str, args: Sequence[object]) -> str:
        """Record the scan and return the event type it asked for."""
        assert "agent_events" in sql, f"expected an agent_events query, got: {sql[:80]}"
        event_type = next((a for a in args if isinstance(a, str) and a != _EXECUTION), None)
        # A session-keyed query binds the id list first, so the event type is
        # the trailing scalar; an execution-keyed one binds the id as $1.
        keyed_by = _SESSION_KEY if any(isinstance(a, list) for a in args) else _EXECUTION_KEY
        resolved = event_type if event_type is not None else _NO_EVENT_TYPE_FILTER
        self.scans.append(_Scan(resolved, keyed_by))
        return resolved

    async def fetch(self, sql: str, *args: object) -> list[dict[str, Any]]:
        event_type = self._record(sql, args)
        if event_type == SESSION_SUMMARY and not self._has_summary:
            return []
        if event_type in (SESSION_SUMMARY, TOKEN_USAGE):
            return [_token_row(event_type)]
        return []

    async def fetchval(self, sql: str, *args: object) -> object:
        self._record(sql, args)
        return 0

    async def __aenter__(self) -> _RecordingConnection:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None


def _token_row(event_type: str) -> dict[str, Any]:
    """One aggregation row, shaped for whichever arm asked for it."""
    row: dict[str, Any] = {
        "session_id": _SESSION,
        "execution_id": _EXECUTION,
        "phase_id": "phase-1",
        "agent_model": "claude-sonnet-4-5",
        "model": "claude-sonnet-4-5",
        "total_input": 100,
        "total_output": 50,
        "cache_creation": 0,
        "cache_read": 0,
        "observation_count": 1,
        "session_count": 1,
        "session_ids": [_SESSION],
        "started_at": datetime(2026, 1, 1, tzinfo=UTC),
        "last_observation": datetime(2026, 1, 1, 0, 1, tzinfo=UTC),
        "workspace_id": "ws-1",
    }
    if event_type == SESSION_SUMMARY:
        row |= {
            "sdk_cost": None,
            "duration_ms_val": 1000,
            "num_turns": 3,
            "total_turns": 3,
            "completed_at": datetime(2026, 1, 1, 0, 1, tzinfo=UTC),
        }
    return row


class _RecordingPool:
    def __init__(self, conn: _RecordingConnection) -> None:
        self._conn = conn

    def acquire(self) -> _RecordingConnection:
        return self._conn


async def _scans_for_session_page(*, has_summary: bool) -> list[_Scan]:
    conn = _RecordingConnection(has_summary=has_summary)
    await TimescaleSessionCostQuery(_RecordingPool(conn)).calculate_many([_SESSION])  # type: ignore[arg-type]
    return conn.scans


async def _scans_for_execution(*, has_summary: bool) -> list[_Scan]:
    conn = _RecordingConnection(has_summary=has_summary)
    await TimescaleExecutionCostQuery(_RecordingPool(conn)).calculate(_EXECUTION)  # type: ignore[arg-type]
    return conn.scans


# The whole remaining set, per read path per branch. Adding an entry here is a
# claim that the new scan is safe at scale; the test below checks the id it
# leads on against that claim.
_EXPECTED: dict[tuple[str, bool], set[_Scan]] = {
    ("session page", True): {
        _Scan(SESSION_SUMMARY, _SESSION_KEY),
        _Scan(TOOL_EXECUTION_COMPLETED, _SESSION_KEY),
        _Scan(SESSION_STARTED, _SESSION_KEY),
    },
    ("session page", False): {
        _Scan(SESSION_SUMMARY, _SESSION_KEY),
        _Scan(TOKEN_USAGE, _SESSION_KEY),
        _Scan(TOOL_EXECUTION_COMPLETED, _SESSION_KEY),
        _Scan(SESSION_STARTED, _SESSION_KEY),
    },
    ("one execution", True): {
        _Scan(SESSION_SUMMARY, _EXECUTION_KEY),
        _Scan(TOOL_EXECUTION_COMPLETED, _EXECUTION_KEY),
        _Scan(_NO_EVENT_TYPE_FILTER, _EXECUTION_KEY),
    },
    ("one execution", False): {
        _Scan(SESSION_SUMMARY, _EXECUTION_KEY),
        _Scan(TOKEN_USAGE, _EXECUTION_KEY),
        _Scan(TOOL_EXECUTION_COMPLETED, _EXECUTION_KEY),
        _Scan(_NO_EVENT_TYPE_FILTER, _EXECUTION_KEY),
    },
}


@pytest.mark.parametrize("has_summary", [True, False], ids=["from_summary", "from_token_usage"])
@pytest.mark.asyncio
async def test_the_agent_events_scans_each_cost_read_path_still_pays_for(
    *, has_summary: bool
) -> None:
    """Pin the exact remaining set, so it cannot grow unnoticed.

    A failure means a cost read path gained or lost an ``agent_events`` scan.
    Losing one is good news and the entry should be deleted; gaining one needs
    the justification above, especially if it is execution-keyed.
    """
    actual = {
        "session page": await _scans_for_session_page(has_summary=has_summary),
        "one execution": await _scans_for_execution(has_summary=has_summary),
    }

    for path, scans in actual.items():
        assert set(scans) == _EXPECTED[path, has_summary], (
            f"{path} (has_summary={has_summary}) changed which agent_events scans it does"
        )


@pytest.mark.asyncio
async def test_no_session_keyed_cost_scan_has_become_execution_keyed() -> None:
    """The session-cost paths must keep leading on the segmentby column.

    This is the property that makes them safe to leave on raw events: a filter
    on ``session_id`` discards whole compressed segments before decompressing
    any of them. Re-keying one of these on ``execution_id`` - which is neither
    segmentby nor orderby - would silently turn a page-bounded read into a
    scan of every chunk in range, while returning identical numbers and
    passing every correctness test.
    """
    for has_summary in (True, False):
        scans = await _scans_for_session_page(has_summary=has_summary)
        assert scans, "the session page must query agent_events at all, or this proves nothing"
        assert all(scan.keyed_by == _SESSION_KEY for scan in scans), (
            f"a session-cost query stopped leading on session_id: "
            f"{[s for s in scans if s.keyed_by != _SESSION_KEY]}"
        )


@pytest.mark.asyncio
async def test_every_execution_keyed_scan_is_recorded_as_outstanding_debt() -> None:
    """#1338's unfixed half, stated as a number rather than a paragraph.

    These are the scans an index cannot help. The count is asserted so that
    converting one to a read model forces this test to be updated - the point
    at which the remaining debt gets restated honestly - and so that a new
    execution-keyed scan cannot pass as maintenance.

    COUNTED PER DISTINCT (event_type, key) SHAPE, not per SQL statement. On the
    summary branch, ``_SESSION_SUMMARY_QUERY`` and ``_COST_BY_PHASE_QUERY`` are
    two separate round-trips that both ask execution_id + session_summary, so
    they collapse to one entry here; the execution path issues five statements
    against agent_events, not three. The shape is what the storage layout
    charges for, so the shape is what this counts - but a reader comparing this
    number to the query constants in ``execution_cost/timescale_query.py``
    should know which of the two they are looking at.
    """
    for has_summary, expected in ((True, 3), (False, 4)):
        scans = await _scans_for_execution(has_summary=has_summary)
        execution_keyed = [s for s in scans if s.keyed_by == _EXECUTION_KEY]
        assert len(set(execution_keyed)) == expected, (
            f"execution-keyed agent_events scans changed (has_summary={has_summary}): "
            f"{sorted(set(execution_keyed))}"
        )
