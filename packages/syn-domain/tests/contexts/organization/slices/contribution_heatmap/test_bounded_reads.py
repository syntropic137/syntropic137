"""The heatmap must not read rows that cannot change what it returns (#1253).

GET /api/v1/insights/contribution-heatmap took 13.6-14.8s in production - the
slowest endpoint in the system by ~5x, on the dashboard landing page - because
its cost tracked the number of ``agent_events`` rows in the window rather than
the number of days it reports.

These tests pin the SHAPE of the statements the query issues: every
"how many distinct X on day D" number must come from the per-day rollup, and
the ONE statement still allowed to touch ``agent_events`` must be narrowed to
the two event types that carry tokens. They are a structural stand-in for the
thing that actually matters, which is rows read; the executed measurement, and
what a DB-level check adds, are at the bottom of this file.

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

if TYPE_CHECKING:
    from collections.abc import Sequence

pytestmark = pytest.mark.unit

_ROLLUP = "agent_event_day_rollup"
_START, _END = date(2026, 3, 5), date(2026, 3, 20)


def _reads_raw_events(statement: str) -> bool:
    """Does this statement read the raw telemetry table at all?"""
    return re.search(r"\bFROM\s+agent_events\b", statement, re.IGNORECASE) is not None


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

    await TimescaleHeatmapQuery(pool).query(_START, _END, {"exec-1"} if filtered else None)
    return issued


def _scans_joined_to_a_session_set(statements: Sequence[str]) -> list[str]:
    """Statements that join ``agent_events`` to a set of sessions.

    Such a join carries a session's rows WHATEVER their timestamps - that is
    deliberate, because a session's summary can land after the window closes -
    so the window is not a predicate on it and nothing else bounds it.
    """
    return [s for s in statements if re.search(r"FROM\s+agent_events\s+a\s+JOIN", s, re.IGNORECASE)]


@pytest.mark.parametrize("filtered", [False, True])
async def test_no_statement_reads_agent_events_without_narrowing_it(filtered: bool) -> None:
    """The ONLY read of raw telemetry may be the usage join, narrowed by type.

    This is the assertion the previous structural guard did not make. It
    required a date predicate, and a date predicate does not bound reads by
    output size - it permits exactly the all-events scans #1253 is about.

    FAILS BEFORE THIS CHANGE, twice over: the executions query read
    ``FROM agent_events`` with only a date range, and ``window_starts`` read
    the same rows again to find which sessions started inside the window.
    """
    statements = await _statements_issued(filtered=filtered)
    assert statements, "query() issued no statements"

    for statement in statements:
        if not _reads_raw_events(statement):
            continue
        assert CANONICAL_USAGE_EVENT_FILTER in statement, (
            "a statement reads agent_events without narrowing it to the event types "
            "that can change its answer; its cost grows with telemetry volume that "
            f"cannot change the heatmap:\n{statement}"
        )


@pytest.mark.parametrize("filtered", [False, True])
async def test_the_distinct_counts_come_from_the_day_rollup(filtered: bool) -> None:
    """executions, commits and session starts must be asked of the rollup.

    Each is a COUNT DISTINCT, and a DISTINCT asked of raw rows costs one read
    per row. Asked of ``agent_event_day_rollup`` - one row per
    (day, session_id, execution_id) - it costs one read per thing the heatmap
    can report.

    FAILS BEFORE THIS CHANGE: no statement mentioned the rollup at all.
    """
    statements = await _statements_issued(filtered=filtered)

    distinct_counts = [s for s in statements if "COUNT(DISTINCT" in s.upper()]
    assert distinct_counts, "expected the executions metric to count distinct executions"
    for statement in distinct_counts:
        assert _ROLLUP in statement, (
            f"a distinct-count is still asked of raw telemetry:\n{statement}"
        )
        assert not _reads_raw_events(statement), (
            f"a distinct-count still reads agent_events:\n{statement}"
        )

    rollup_readers = [s for s in statements if _ROLLUP in s]
    assert len(rollup_readers) == len(statements), (
        "every heatmap statement should be anchored on the rollup; "
        f"{len(statements) - len(rollup_readers)} are not"
    )


async def test_commits_are_a_summed_rollup_column_not_a_scan() -> None:
    """``commits`` must not ride on a scan of every event in the window.

    FAILS BEFORE #1253: commits were a ``COUNT(*) FILTER (WHERE event_type =
    'git_commit')`` on the query that reads every row in the window, so the
    cheap metric cost what the expensive one costs. It is now a column the
    trigger maintains, summed per day.
    """
    statements = await _statements_issued(filtered=False)

    commit_scans = [s for s in statements if re.search(r"\bcommits\b", s)]
    assert len(commit_scans) == 1, (
        f"expected exactly one statement to report commits, got {len(commit_scans)}"
    )
    statement = commit_scans[0]

    assert re.search(r"SUM\(commits\)", statement, re.IGNORECASE), (
        f"commits must be summed from the rollup column:\n{statement}"
    )
    assert not _reads_raw_events(statement), (
        f"the commit count must not read agent_events:\n{statement}"
    )
    assert "COUNT(DISTINCT" not in statement.upper(), (
        f"the commit statement must not also carry another metric:\n{statement}"
    )


# WHAT WAS MEASURED, AND WHAT A DB-LEVEL CHECK STILL ADDS.
#
# These tests constrain the statements. They cannot observe rows read, and
# rows read is the property #1253 is about. That was measured directly while
# preparing this change, against a real PostgreSQL 16 driven by `pgserver`,
# with the old statements read out of the pre-change commit so both sides ran
# on ONE database. That harness is not committed - it is the gap named in the
# #1253 report, and closing it is the remaining work on this issue.
#
# Old statements and new run against ONE seeded database covering a session
# starting before the window, a summary landing after it, a session crossing
# midnight, a failed session with no usage, duplicate and all-zero summaries,
# an unresolvable model (#788), a NULL execution_id and a session id reused
# across executions. Output is identical for every metric across five
# execution scopes: 20/20 comparisons equal.
#
# Rows processed by the plan, before and after adding 20,000 events of a type
# no metric counts, to a session and execution that already appear (so the
# output cannot move, and does not):
#
#     old activity    52 ->  40,052      new executions   41 -> 1,238
#     old sessions   185 -> 100,169      new commits      35 -> 1,216
#     old usage      391 -> 100,234      new sessions     66 -> 1,245
#                                        new usage       262 -> 1,371
#
# The old statements take ~100% of the added rows; the new ones take ~6% of
# them. The residual is not zero and this comment does not claim it is: 20,000
# inserts update the same handful of rollup rows, and that churn is visible to
# the next scan. It was not isolated further before this was written.
#
# A check of this shape inside the test suite would measure the property
# directly rather than by proxy, and would catch the two things no string
# assertion can see: a planner that ignores an index, and TimescaleDB
# decompressing a chunk to satisfy a predicate the index should have answered.
# It is not in the suite because CI's PR gate runs `pytest -m unit`, which
# provisions no database.
