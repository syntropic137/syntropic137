"""The heatmap must not read rows that cannot change what it returns (#1253).

GET /api/v1/insights/contribution-heatmap took 13.6-14.8s in production - the
slowest endpoint in the system by ~5x, on the dashboard landing page - because
its cost tracked the number of ``agent_events`` rows in the window rather than
the number of days it reports.

These tests pin the SHAPE of the statements the query issues. They are a
structural stand-in for the thing that actually matters, which is rows read;
what a DB-level check adds, and why one is not here, is at the bottom of this
file.

WHAT EACH ASSERTION CATCHES. Every one of them fails against the pre-#1253
implementation, for a stated reason - not because the text changed.
"""

from __future__ import annotations

import re
from datetime import date
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest

from syn_domain.contexts.agent_sessions import CANONICAL_USAGE_EVENT_FILTER
from syn_domain.contexts.organization.slices.contribution_heatmap.TimescaleHeatmapQuery import (
    TimescaleHeatmapQuery,
)
from syn_shared.events import GIT_COMMIT

if TYPE_CHECKING:
    from collections.abc import Sequence

pytestmark = pytest.mark.unit

_WINDOW_BOUND = re.compile(r"time\s*>=\s*\$1::date", re.IGNORECASE)
_START, _END = date(2026, 3, 5), date(2026, 3, 20)


async def _statements_issued(*, filtered: bool) -> list[str]:
    """Every SQL statement one ``query()`` call actually sends.

    Reads what the query EXECUTES rather than what the module declares: a
    template narrowed in the module but not passed to the connection would
    satisfy the second and fail real traffic.
    """
    issued: list[str] = []

    async def _fetch(sql: str, *_args: object) -> list[object]:
        issued.append(sql)
        return []

    conn = MagicMock()
    conn.fetch = AsyncMock(side_effect=_fetch)
    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

    await TimescaleHeatmapQuery(pool).query(
        _START, _END, {"exec-1"} if filtered else None
    )
    return issued


def _scans_joined_to_a_session_set(statements: Sequence[str]) -> list[str]:
    """Statements that join ``agent_events`` to a set of sessions.

    Such a join carries a session's rows WHATEVER their timestamps - that is
    deliberate, because a session's summary can land after the window closes -
    so the window is not a predicate on it and nothing else bounds it.
    """
    return [
        s
        for s in statements
        if re.search(r"FROM\s+agent_events\s+a\s+JOIN", s, re.IGNORECASE)
    ]


@pytest.mark.parametrize("filtered", [False, True])
async def test_no_statement_loads_a_session_s_whole_history(filtered: bool) -> None:
    """Joining back to a session's rows must select only the usage event types.

    FAILS BEFORE #1253: ``scoped_events`` joined every row of every member
    session - tool calls, stream chunks, and the JSONB ``data`` blob on each -
    and three CTEs read it, so PostgreSQL could not inline it and materialised
    the lot into a work table to total the two event types that carry tokens.
    """
    joined = _scans_joined_to_a_session_set(await _statements_issued(filtered=filtered))

    assert joined, "expected the usage query to join agent_events to its member sessions"
    for statement in joined:
        assert CANONICAL_USAGE_EVENT_FILTER in statement, (
            "an unbounded join to session history must select only the event types "
            f"canonical usage reads; got:\n{statement}"
        )


@pytest.mark.parametrize("filtered", [False, True])
async def test_every_other_scan_is_bounded_by_the_window(filtered: bool) -> None:
    """Scans that are not narrowed to a session set must carry the date bound.

    FAILS BEFORE #1253 for the sessions and usage queries: both built
    ``scoped_events`` from an unqualified ``FROM agent_events a JOIN ...``
    whose only predicate was the optional execution filter.
    """
    statements = await _statements_issued(filtered=filtered)
    joined = set(_scans_joined_to_a_session_set(statements))

    for statement in statements:
        if statement in joined:
            continue
        assert _WINDOW_BOUND.search(statement), (
            f"unjoined scan of agent_events with no date bound:\n{statement}"
        )


async def test_commits_are_counted_by_a_scan_the_event_type_index_can_serve() -> None:
    """``commits`` must not ride on the scan that counts executions.

    FAILS BEFORE #1253: commits were a ``COUNT(*) FILTER (WHERE event_type =
    'git_commit')`` on the query that reads every row in the window, so the
    cheap metric cost what the expensive one costs. Leading with a constant
    ``event_type`` lets idx_events_type (event_type, time DESC) turn the window
    into a range on its second column, which reads commits and not telemetry.
    """
    statements = await _statements_issued(filtered=False)

    commit_scans = [s for s in statements if GIT_COMMIT in s]
    assert len(commit_scans) == 1, (
        f"expected exactly one statement to mention {GIT_COMMIT}, got {len(commit_scans)}"
    )
    statement = commit_scans[0]

    assert re.search(rf"WHERE\s+event_type\s*=\s*'{GIT_COMMIT}'", statement), (
        f"commits must be selected by a leading constant event_type:\n{statement}"
    )
    assert "FILTER" not in statement.upper(), (
        f"commits must not be a FILTER over a wider scan:\n{statement}"
    )
    assert "COUNT(DISTINCT" not in statement.upper(), (
        f"the commit scan must not also carry another metric:\n{statement}"
    )


# WHAT A DB-LEVEL CHECK WOULD ADD, AND WHY IT IS NOT HERE.
#
# These tests constrain the statements. They cannot observe rows read, and
# rows read is the property #1253 is about. A check against a real database -
# seed the window, run EXPLAIN (ANALYZE, BUFFERS), add N rows of event types
# no metric reads to sessions and executions that already appear, re-run, and
# assert the count did not grow by N - would measure the property directly,
# and would additionally catch the two things no string can see: a planner
# that ignores an index, and TimescaleDB decompressing a chunk to satisfy a
# predicate the index should have answered.
#
# It is not here because CI's PR gate runs `pytest -m unit`, which provisions
# no database. Run against PostgreSQL 16 while preparing this change, that
# measurement gave, for a 16-day window with 20,000 non-contributing rows
# added inside it:
#
#     old activity   20,021 rows ->  new executions  20,021   (unchanged)
#                                    new commits          3   (bounded)
#     old sessions   40,037 rows ->  new sessions    20,021
#     old usage      40,037 rows ->  new usage       20,034
#
# Which is the honest result: the joins back to session history are gone, and
# commits is bounded, but `executions` and the window scan that finds session
# starts still grow with raw telemetry volume. Bounding those needs a per-day
# rollup, not a better statement - see the note at `_EXECUTIONS_QUERY`.
