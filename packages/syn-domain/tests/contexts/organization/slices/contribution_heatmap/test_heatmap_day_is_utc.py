"""A heatmap square is a UTC day, whoever wrote the event and whoever reads it.

WHAT WENT WRONG (#1371)

``agent_event_day_rollup.day`` was ``time_bucket('1 day', NEW.time)::date``.
``time_bucket`` over a ``timestamptz`` returns a ``timestamptz``, and casting
one to ``date`` resolves in the CONNECTION's ``TimeZone``. Nothing pins that -
asyncpg inherits the server default - so the day an event was filed under was a
fact about whoever happened to insert it. The trigger sees each event once, so
that row can never be re-decided: get it wrong and it is wrong for good.

The read side had the same cast in ``started_at::date``, which decides the day
a SESSION is counted on. A reader in a different zone from the writer therefore
attributed sessions to a day whose executions and commits had been filed by a
different rule - one square short, the neighbour one long.

WAS THE OLD (PRE-#1253) QUERY ALSO ZONE-DEPENDENT? YES, AND WORSE.

It is worth stating plainly because it decides how this file is written. The
legacy implementation bounded its window with ``time >= $1::date`` - a DATE
promoted to midnight in the SESSION's zone - while bucketing the rows it found
with ``time_bucket(...)::date``, and attributing sessions with
``started_at::date``. All three move with the connection, so under
``America/Los_Angeles`` the legacy query does not merely disagree with the new
one, it disagrees with ITSELF run under UTC. ``test_it_was_zone_dependent_too``
below demonstrates that rather than asserting it from the source.

Two consequences:

  - the legacy implementation is NOT a zone-independent oracle, so this file
    does not compare against it. It compares against ``_EXPECTED``, computed in
    Python from the instants seeded - an answer that exists before either
    implementation runs and cannot be produced by either being wrong.
  - the equivalence test next door (test_heatmap_rollup_equivalence.py) must
    keep pinning BOTH its pools to UTC, which it does and documents. Comparing
    old against new under a non-UTC session would measure that pre-existing
    defect in the old query instead of the change under test.

WHAT IS SEEDED

Three instants, each chosen so the zones under test disagree about its day:

  2023-05-10T00:30Z   the window's first UTC day. Under UTC-7 it is May 9,
                      BEFORE the window: the broken read drops it entirely.
  2023-05-20T23:30Z   the window's last UTC day. Under UTC+5:30 it is May 21,
                      AFTER the window: dropped from the other end.
  2023-05-15T12:00Z   mid-window, where every zone agrees. The control - if it
                      moved, something other than the boundary rule broke.

Each is seeded twice: once before ``ensure_schema()`` creates the rollup, so it
arrives through the BACKFILL, and once after, so it arrives through the
TRIGGER. Both statements carried the defect and both had to be fixed, so both
are asked. That is why every expected count below is 2.

MARKED ``integration``: this needs a real PostgreSQL to have a session time
zone at all. That job runs on schedule, workflow_dispatch, push to main and PRs
into ``release`` - not on a PR into ``main``. The statement-level half that
does gate a PR is packages/syn-adapters/tests/events/test_day_rollup_utc_day.py.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest

from syn_domain.contexts.organization.slices.contribution_heatmap.TimescaleHeatmapQuery import (
    TimescaleHeatmapQuery,
)
from syn_shared.events import GIT_COMMIT, SESSION_STARTED

from .legacy_heatmap_query_pre_1253 import LegacyTimescaleHeatmapQuery

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    import asyncpg
    from syn_tests.fixtures.infrastructure import TestInfrastructure

pytestmark = pytest.mark.integration


WINDOW_START = date(2023, 5, 10)
WINDOW_END = date(2023, 5, 20)

#: Prefixes, so teardown - and the next run, if a teardown was skipped - can
#: find every row this module wrote without knowing which run wrote it. Distinct
#: from the equivalence test's, so neither can clean up the other's rows.
SESSION_PREFIX = "hutc-"
EXECUTION_PREFIX = "hutx-"

_RUN = uuid4().hex[:8]

#: UTC, a negative offset and a positive one. Kolkata is +05:30 on purpose: a
#: half-hour offset breaks any fix that quietly assumed whole hours.
ZONES = ("UTC", "America/Los_Angeles", "Asia/Kolkata")

#: instant -> the UTC day it belongs to. The right-hand side is the assertion;
#: it is written out rather than derived from the left so that a change to the
#: derivation cannot move the expectation with it.
SEEDED = {
    datetime(2023, 5, 10, 0, 30, tzinfo=UTC): "2023-05-10",
    datetime(2023, 5, 15, 12, 0, tzinfo=UTC): "2023-05-15",
    datetime(2023, 5, 20, 23, 30, tzinfo=UTC): "2023-05-20",
}

#: Two of everything on each of those days: one row through the backfill, one
#: through the trigger.
_EXPECTED = dict.fromkeys(SEEDED.values(), 2)


def _sid(instant: datetime, path: str) -> str:
    return f"{SESSION_PREFIX}{_RUN}-{instant:%m%d%H%M}-{path}"


def _eid(instant: datetime, path: str) -> str:
    return f"{EXECUTION_PREFIX}{_RUN}-{instant:%m%d%H%M}-{path}"


ALL_EXECUTIONS = {_eid(at, path) for at in SEEDED for path in ("backfill", "trigger")}


def _zoned(dsn: str, zone: str) -> str:
    """The same DSN with the session's time zone pinned.

    asyncpg forwards unrecognised DSN query parameters as server settings, so
    this reaches whatever pool is built from it - the WRITER's as much as the
    reader's, and the writer's is the one that used to decide what `day` meant.
    """
    return f"{dsn}{'&' if '?' in dsn else '?'}timezone={zone}"


async def _seed(conn: asyncpg.pool.PoolConnectionProxy, path: str) -> None:
    """One session and one execution per instant, each starting and committing.

    Raw SQL rather than ``AgentEventStore``: the point is which CONNECTION
    performs the INSERT, because that is the session whose zone the trigger
    used to resolve in, and a store builds its own pool.
    """
    for at in SEEDED:
        for offset, event_type in enumerate((SESSION_STARTED, GIT_COMMIT)):
            await conn.execute(
                "INSERT INTO agent_events (time, event_type, session_id, execution_id, data) "
                "VALUES ($1, $2, $3, $4, '{}'::jsonb)",
                at + timedelta(seconds=offset),
                event_type,
                _sid(at, path),
                _eid(at, path),
            )


async def _forget_seeded_rows(conn: asyncpg.pool.PoolConnectionProxy) -> None:
    """Remove every row this module has ever written, from both tables.

    Run before seeding as well as after: a run killed mid-test leaves rows the
    next run would count twice. The rollup is cleaned explicitly because the
    trigger is AFTER INSERT - deleting the events alone leaves it claiming
    sessions that no longer exist.
    """
    await conn.execute("DELETE FROM agent_events WHERE session_id LIKE $1", f"{SESSION_PREFIX}%")
    if await conn.fetchval("SELECT to_regclass('agent_event_day_rollup') IS NOT NULL") is True:
        await conn.execute(
            "DELETE FROM agent_event_day_rollup WHERE session_id LIKE $1", f"{SESSION_PREFIX}%"
        )


@pytest.fixture(params=ZONES, ids=lambda zone: f"written-in-{zone}")
async def writer_zone(
    request: pytest.FixtureRequest, test_infrastructure: TestInfrastructure
) -> AsyncGenerator[str, None]:
    """Seed the whole fixture through a writer pinned to one zone.

    The rollup is dropped and rebuilt so that half the seed reaches it through
    the backfill and half through the trigger - both statements had the defect.
    Rebuilt per zone rather than once per module, because the whole question is
    which zone was in effect when each row was written.
    """
    import asyncpg

    from syn_adapters.events import AgentEventStore
    from syn_adapters.events.schema import EventStoreSchema

    dsn = _zoned(test_infrastructure.timescaledb_url, request.param)

    store = AgentEventStore(dsn)
    await store.initialize()  # agent_events must exist before the raw inserts
    await store.close()

    pool = await asyncpg.create_pool(dsn)
    assert pool is not None
    try:
        async with pool.acquire() as conn:
            await _forget_seeded_rows(conn)
            await conn.execute("DROP TRIGGER IF EXISTS agent_events_day_rollup ON agent_events")
            await conn.execute("DROP TABLE IF EXISTS agent_event_day_rollup")

            await _seed(conn, "backfill")
            await EventStoreSchema().ensure_schema(conn)  # rebuilds it, and backfills
            await _seed(conn, "trigger")
        yield request.param
    finally:
        async with pool.acquire() as conn:
            await _forget_seeded_rows(conn)
        await pool.close()


async def _heatmap_read_in(dsn: str, zone: str) -> dict[str, dict[str, float]]:
    """Run the current heatmap through a reader pinned to ``zone``."""
    import asyncpg

    pool = await asyncpg.create_pool(_zoned(dsn, zone))
    assert pool is not None
    try:
        days = await TimescaleHeatmapQuery(pool).query(WINDOW_START, WINDOW_END, ALL_EXECUTIONS)
    finally:
        await pool.close()
    return {day.date: day.breakdown for day in days}


class TestTheDayIsTheEventsUTCDay:
    @pytest.mark.parametrize("reader_zone", ZONES)
    async def test_every_metric_lands_on_the_utc_day(
        self, writer_zone: str, reader_zone: str, test_infrastructure: TestInfrastructure
    ) -> None:
        """Nine combinations, one answer.

        Compared against ``_EXPECTED``, computed from the seeded instants rather
        than from a query - so agreement cannot come from both sides being wrong
        in the same direction, which is exactly what a writer and a reader
        sharing a zone would produce.
        """
        breakdowns = await _heatmap_read_in(test_infrastructure.timescaledb_url, reader_zone)

        for metric in ("sessions", "executions", "commits"):
            actual = {
                day: int(breakdown[metric])
                for day, breakdown in breakdowns.items()
                if breakdown[metric]
            }
            assert actual == _EXPECTED, (
                f"{metric} written in {writer_zone}, read in {reader_zone}: the "
                f"heatmap put activity on {sorted(actual)} when the events "
                f"happened on {sorted(_EXPECTED)} UTC. A square is a UTC day "
                "(#1371)."
            )

    async def test_the_window_edges_are_the_cases_that_move(
        self, writer_zone: str, test_infrastructure: TestInfrastructure
    ) -> None:
        """Named separately so a failure says WHICH end came loose.

        The mid-window control is in ``_EXPECTED`` above and every zone agrees
        about it, so a run where only it survives is a boundary bug and a run
        where it too is missing is something else - a seed that never landed, a
        window off by a day.
        """
        breakdowns = await _heatmap_read_in(test_infrastructure.timescaledb_url, "UTC")

        assert breakdowns["2023-05-10"]["sessions"] == 2, (
            "an event at 00:30Z on the window's first day is missing. Under a "
            "negative-offset writer that instant used to be filed under the "
            "previous day, which is outside the window entirely"
        )
        assert breakdowns["2023-05-20"]["sessions"] == 2, (
            "an event at 23:30Z on the window's last day is missing. Under a "
            "positive-offset writer that instant used to be filed under the "
            "next day, which is outside the window entirely"
        )


class TestWhyThisFileDoesNotCompareAgainstTheOldQuery:
    async def test_it_was_zone_dependent_too(
        self, writer_zone: str, test_infrastructure: TestInfrastructure
    ) -> None:
        """The pre-#1253 implementation disagrees with ITSELF across zones.

        Demonstrated rather than asserted from the source, because it is the
        premise of two things: that this file compares against a computed
        expectation, and that test_heatmap_rollup_equivalence.py must pin both
        of its pools to UTC. If this ever stops failing to agree, the legacy
        query has become a zone-independent oracle and both of those choices
        are worth revisiting.
        """
        import asyncpg

        answers = {}
        for zone in ("UTC", "America/Los_Angeles"):
            pool = await asyncpg.create_pool(_zoned(test_infrastructure.timescaledb_url, zone))
            assert pool is not None
            try:
                days = await LegacyTimescaleHeatmapQuery(pool).query(
                    WINDOW_START, WINDOW_END, ALL_EXECUTIONS
                )
            finally:
                await pool.close()
            answers[zone] = {
                day.date: int(day.breakdown["sessions"])
                for day in days
                if day.breakdown["sessions"]
            }

        assert answers["UTC"] != answers["America/Los_Angeles"], (
            "the legacy heatmap gave the same answer in both zones, so it "
            "could after all serve as an oracle here - see this class's name"
        )
