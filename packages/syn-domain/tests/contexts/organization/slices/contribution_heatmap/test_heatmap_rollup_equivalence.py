"""#1253 changed what the heatmap COSTS. This proves it did not change what it SAYS.

WHY THIS ONE HAD TO BE A DATABASE TEST

Before #1253 the heatmap's numbers came out of SQL you could read: statements
over ``agent_events``. They now come out of ``agent_event_day_rollup``, a table
maintained by an AFTER INSERT trigger and first populated by a backfill. Two of
the three things that can now be wrong - the trigger's upsert arithmetic and
the backfill's GROUP BY - are SQL that only PostgreSQL executes. A test with a
mocked connection can assert which statement was sent; it cannot tell you that
``SUM(commits)`` off the rollup equals ``COUNT(*) FILTER (WHERE event_type =
'git_commit')`` off the raw rows, because nothing in it ever runs either one.

So this runs both implementations against one real database and compares their
output. ``legacy_heatmap_query_pre_1253.py`` is the frozen pre-change
implementation - read its docstring before changing anything here. It is the
specification: a change of cost that changes an answer is a bug.

WHAT IS SEEDED, AND WHY EACH PIECE IS THERE

Every row below exists to make old and new disagree if the rollup is wrong:

  multiple sessions on one day   the rollup is keyed on
                                 (day, session, execution), so two sessions on
                                 one day are two rows; an upsert that collapsed
                                 them would lose one from the count
  a session crossing midnight    two rollup rows for one session. A session is
                                 counted on the day it STARTED, so
                                 MIN(first_time) has to win across those rows -
                                 summing per-day counts would count it twice
  a session starting BEFORE the  the anti-join's whole job. It must not count
  window and reaching into it    as a session of any day in the window, while
                                 its execution and its commit still appear on
                                 the in-window day they landed on
  a summary arriving AFTER the   canonical usage must still price from it, so
  window ends                    the usage join must NOT be bounded by time
  commits, several per day       ``commits`` is the only ACCUMULATING column in
                                 the rollup, and so the only one an upsert can
                                 get wrong by overwriting instead of adding
  tool events in bulk            rows the new path must never read. They change
                                 no output, so any disagreement they cause is
                                 the rollup counting the wrong thing

and - the part no pure-SQL reading would cover - the rows arrive in TWO
batches: one while the rollup does not exist, reaching it through the BACKFILL,
and one after it does, reaching it through the TRIGGER. Those are two separate
pieces of SQL which have to agree with each other as well as with the old
implementation, and half the seeded sessions go through each.

Both batches are written with ``AgentEventStore.insert_batch``, which is COPY.
That is deliberate: the claim that justified a trigger rather than an
application hook is that COPY bypasses application hooks, and this is where
that claim gets tested.

TIME ZONE. Both pools below pin their session to UTC, and the writing pool
matters as much as the reading one: the trigger computes
``time_bucket('1 day', NEW.time)::date`` in the INSERTING session's zone. The
old implementation bounded its window with ``time >= $1::date`` (midnight,
session zone) while bucketing with ``time_bucket`` (UTC); the new one compares
a date to a date. Under a non-UTC session those two spellings can disagree at a
window edge - a pre-existing mismatch inside the OLD query, not something #1253
introduced. Pinning UTC keeps this file measuring the change under test.

MARKED ``integration``, so it does NOT gate a PR into main: that job runs on
schedule, workflow_dispatch, push to main, and PRs into ``release``. It gates
the release and it runs on merge.
"""

from __future__ import annotations

import time as clock
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, Any
from uuid import uuid4

import pytest

from syn_domain.contexts.organization._shared.projection_names import REPO_CORRELATION
from syn_domain.contexts.organization.domain.queries.get_contribution_heatmap import (
    VALID_METRICS,
    GetContributionHeatmapQuery,
)
from syn_domain.contexts.organization.slices.conftest import FakeProjectionStore
from syn_domain.contexts.organization.slices.contribution_heatmap.GetContributionHeatmapHandler import (
    GetContributionHeatmapHandler,
)
from syn_domain.contexts.organization.slices.contribution_heatmap.TimescaleHeatmapQuery import (
    TimescaleHeatmapQuery,
)
from syn_domain.contexts.organization.slices.list_repos.projection import RepoProjection
from syn_shared.events import GIT_COMMIT, SESSION_STARTED, SESSION_SUMMARY, TOKEN_USAGE

from .legacy_heatmap_query_pre_1253 import LegacyTimescaleHeatmapQuery

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    import asyncpg
    from syn_tests.fixtures.infrastructure import TestInfrastructure

    from syn_domain.contexts.organization.domain.read_models.contribution_heatmap import (
        HeatmapDayBucket,
    )

pytestmark = pytest.mark.integration


# A window far from `now()`. Every other integration test in this repo writes
# on today's date, so a historic window is what makes the UNFILTERED comparison
# below a comparison of this file's rows. Fixed rather than relative, so a
# failure reproduces.
WINDOW_START = date(2023, 5, 10)
WINDOW_END = date(2023, 5, 20)

# Prefixes, so teardown - and the next run, if a teardown was skipped - can
# find every row this module wrote without knowing which run wrote it.
SESSION_PREFIX = "heq-"
EXECUTION_PREFIX = "hex-"

_RUN = uuid4().hex[:8]

ORG_ID = f"org-{_RUN}"
SYSTEM_ONE = f"sys1-{_RUN}"
SYSTEM_TWO = f"sys2-{_RUN}"

REPO_ALPHA = f"acme/alpha-{_RUN}"
REPO_BETA = f"acme/beta-{_RUN}"
REPO_GAMMA = f"other/gamma-{_RUN}"

EXEC_A1 = f"{EXECUTION_PREFIX}{_RUN}-a1"
EXEC_A2 = f"{EXECUTION_PREFIX}{_RUN}-a2"
EXEC_B1 = f"{EXECUTION_PREFIX}{_RUN}-b1"
EXEC_G1 = f"{EXECUTION_PREFIX}{_RUN}-g1"

# repo_id -> (full_name, system_id). Ids are explicit because two systems share
# one store here: `_make_projections` in slices/conftest.py numbers repos from
# zero per call, so seeding a second system through it would overwrite `repo-0`
# - alpha would silently become gamma and the org scope would assert on rows
# nobody seeded.
_REPOS = {
    f"repo-alpha-{_RUN}": (REPO_ALPHA, SYSTEM_ONE),
    f"repo-beta-{_RUN}": (REPO_BETA, SYSTEM_ONE),
    f"repo-gamma-{_RUN}": (REPO_GAMMA, SYSTEM_TWO),
}
REPO_ID_ALPHA = f"repo-alpha-{_RUN}"

_CORRELATIONS = {
    EXEC_A1: REPO_ALPHA,
    EXEC_A2: REPO_ALPHA,
    EXEC_B1: REPO_BETA,
    EXEC_G1: REPO_GAMMA,
}


def _at(day_offset: int, hour: int = 12, minute: int = 0) -> datetime:
    """A UTC instant ``day_offset`` days from the window's first day."""
    return datetime.combine(
        WINDOW_START + timedelta(days=day_offset), datetime.min.time(), tzinfo=UTC
    ).replace(hour=hour, minute=minute)


# The shape the production write path takes: `AgentEventStore.insert_batch`
# is typed `list[dict[str, Any]]` and `AgentEvent.from_dict` reads it by key.
# This file exists to drive THAT path, so the seed has to speak its language -
# a dataclass here would have to be unpacked into these dicts before the call
# and would type nothing that reaches the database. Named once so the erasure
# is declared in one place rather than at each of the eleven use sites below.
SeedEvent = dict[str, Any]


def _sid(name: str) -> str:
    return f"{SESSION_PREFIX}{_RUN}-{name}"


def _started(session: str, execution: str, at: datetime) -> SeedEvent:
    return {
        "time": at,
        "event_type": SESSION_STARTED,
        "session_id": session,
        "execution_id": execution,
        "provider": "claude",
    }


def _tokens(
    session: str,
    execution: str,
    at: datetime,
    *,
    model: str = "claude-sonnet-4-5",
    output_tokens: int = 5,
) -> SeedEvent:
    """One per-turn usage row. ``output_tokens`` is a PLACEHOLDER (#932)."""
    return {
        "time": at,
        "event_type": TOKEN_USAGE,
        "session_id": session,
        "execution_id": execution,
        "model": model,
        "input_tokens": 1000,
        "output_tokens": output_tokens,
        "cache_creation_tokens": 120,
        "cache_read_tokens": 3400,
    }


def _summary(
    session: str,
    execution: str,
    at: datetime,
    *,
    model: str = "claude-sonnet-4-5",
    vendor_cost: str | None = "0.0944",
) -> SeedEvent:
    """The authoritative end-of-session record, which supersedes the turn rows."""
    event: SeedEvent = {
        "time": at,
        "event_type": SESSION_SUMMARY,
        "session_id": session,
        "execution_id": execution,
        "model": model,
        "total_input_tokens": 41000,
        "total_output_tokens": 13300,
        "cache_creation_tokens": 900,
        "cache_read_tokens": 250000,
    }
    if vendor_cost is not None:
        event["total_cost_usd"] = vendor_cost
    return event


def _commit(session: str, execution: str, at: datetime, sha: str) -> SeedEvent:
    """A commit observation.

    No ``message`` key: ``AgentEvent.from_dict`` reads ``message`` as a Claude
    content envelope and calls ``.get`` on it, so a plain string there raises,
    and ``insert_batch`` logs the failure and SKIPS the row. A commit silently
    absent from both implementations would let the whole file agree on nothing.
    """
    return {
        "time": at,
        "event_type": GIT_COMMIT,
        "session_id": session,
        "execution_id": execution,
        "sha": sha,
    }


def _noise(session: str, execution: str, at: datetime, count: int) -> list[SeedEvent]:
    """Telemetry the heatmap must ignore. In bulk, because bulk is the problem."""
    return [
        {
            "time": at + timedelta(seconds=i),
            "event_type": "tool_execution_started",
            "session_id": session,
            "execution_id": execution,
            "tool_name": "Read",
            "tool_use_id": f"{session}-{i}",
        }
        for i in range(count)
    ]


def _events_reaching_the_rollup_by_backfill() -> list[SeedEvent]:
    """Seeded while no rollup exists, so only the backfill can account for them."""
    events: list[SeedEvent] = []

    # Two sessions, ONE day, ONE execution. Both must be counted.
    one = _sid("pre-1")
    events += [
        _started(one, EXEC_A1, _at(1, 9)),
        _tokens(one, EXEC_A1, _at(1, 9, 30)),
        _summary(one, EXEC_A1, _at(1, 10)),
        _commit(one, EXEC_A1, _at(1, 9, 40), "aaa1"),
        _commit(one, EXEC_A1, _at(1, 9, 50), "aaa2"),
        *_noise(one, EXEC_A1, _at(1, 9, 5), 40),
    ]
    two = _sid("pre-2")
    events += [
        _started(two, EXEC_A1, _at(1, 11)),
        # No summary, and a different model: priced from its turn rows.
        _tokens(two, EXEC_A1, _at(1, 11, 15), output_tokens=760, model="claude-opus-4-1"),
        _commit(two, EXEC_A1, _at(1, 11, 30), "bbb1"),
    ]

    # Crosses midnight: starts 23:30 on day 2, still emitting on day 3.
    three = _sid("pre-3")
    events += [
        _started(three, EXEC_A2, _at(2, 23, 30)),
        _tokens(three, EXEC_A2, _at(2, 23, 45)),
        _tokens(three, EXEC_A2, _at(3, 0, 20)),
        _summary(three, EXEC_A2, _at(3, 0, 30)),
        _commit(three, EXEC_A2, _at(3, 0, 25), "ccc1"),
        *_noise(three, EXEC_A2, _at(2, 23, 31), 25),
    ]

    # No commits, no summary, a third repo's execution.
    four = _sid("pre-4")
    events += [
        _started(four, EXEC_B1, _at(4, 14)),
        _tokens(four, EXEC_B1, _at(4, 14, 10), output_tokens=91),
    ]

    # Starts four days BEFORE the window and reaches into it.
    edge = _sid("pre-edge")
    events += [
        _started(edge, EXEC_A2, _at(-4, 8)),
        _tokens(edge, EXEC_A2, _at(-4, 8, 30)),
        _tokens(edge, EXEC_A2, _at(2, 16)),
        _commit(edge, EXEC_A2, _at(2, 16, 5), "ddd1"),
        _summary(edge, EXEC_A2, _at(2, 17)),
    ]
    return events


def _events_reaching_the_rollup_by_trigger() -> list[SeedEvent]:
    """Seeded once the rollup exists, so only the trigger can account for them."""
    events: list[SeedEvent] = []

    five = _sid("post-1")
    events += [
        _started(five, EXEC_A1, _at(5, 8)),
        _tokens(five, EXEC_A1, _at(5, 8, 20)),
        _summary(five, EXEC_A1, _at(5, 9), vendor_cost="0.3312"),
        _commit(five, EXEC_A1, _at(5, 8, 30), "eee1"),
        _commit(five, EXEC_A1, _at(5, 8, 40), "eee2"),
        _commit(five, EXEC_A1, _at(5, 8, 50), "eee3"),
        *_noise(five, EXEC_A1, _at(5, 8, 1), 60),
    ]
    six = _sid("post-2")
    events += [
        _started(six, EXEC_A1, _at(5, 20)),
        _tokens(six, EXEC_A1, _at(5, 20, 5), output_tokens=430),
    ]

    seven = _sid("post-3")
    events += [
        _started(seven, EXEC_B1, _at(6, 22)),
        _tokens(seven, EXEC_B1, _at(6, 22, 30)),
        _tokens(seven, EXEC_B1, _at(7, 1)),
        # Codex never reports a cost: this session must be priced from tokens.
        _summary(seven, EXEC_B1, _at(7, 2), vendor_cost=None),
        _commit(seven, EXEC_B1, _at(7, 1, 30), "fff1"),
    ]

    eight = _sid("post-4")
    events += [
        _started(eight, EXEC_G1, _at(8, 11)),
        _tokens(eight, EXEC_G1, _at(8, 11, 20)),
        _commit(eight, EXEC_G1, _at(8, 11, 40), "ggg1"),
    ]

    # Starts inside the window; its authoritative summary lands three days
    # AFTER the window ends. Pricing must still come from that summary.
    tail = _sid("post-tail")
    events += [
        _started(tail, EXEC_B1, _at(9, 15)),
        _tokens(tail, EXEC_B1, _at(9, 15, 10)),
        _summary(tail, EXEC_B1, _at(13, 4), vendor_cost="1.2500"),
        *_noise(tail, EXEC_B1, _at(9, 15, 11), 30),
    ]
    return events


SEEDED_SESSIONS = 10
"""Ten sessions are written. `pre-edge` started before the window, so nine count."""

SEEDED_COMMITS = 10
"""Every commit lands on an in-window day, including `pre-edge`'s (#1253: an
activity marker belongs to the day it happened, whoever's session it was)."""


def _utc(dsn: str) -> str:
    """The same DSN, with the session's time zone pinned.

    asyncpg forwards unrecognised DSN query parameters as server settings, so
    this reaches the store's own pool - which is the one that matters most: the
    trigger casts ``time_bucket(...)::date`` in the zone of the session doing
    the INSERT, so an unpinned writer decides what `day` means.
    """
    return f"{dsn}{'&' if '?' in dsn else '?'}timezone=UTC"


@dataclass
class SeededHeatmap:
    """One database holding both halves of the seed, and both implementations."""

    dsn: str
    pool: asyncpg.Pool
    store: FakeProjectionStore
    repo_projection: RepoProjection

    def new(self) -> TimescaleHeatmapQuery:
        return TimescaleHeatmapQuery(self.pool)

    def legacy(self) -> LegacyTimescaleHeatmapQuery:
        return LegacyTimescaleHeatmapQuery(self.pool)


async def _forget_seeded_rows(conn: asyncpg.pool.PoolConnectionProxy) -> None:
    """Remove every row this module has ever written, from both tables.

    Run before seeding as well as after. A run killed mid-test leaves rows in a
    window the unfiltered comparison counts exactly, and the next run would
    then fail on a number it did not write. The rollup is cleaned explicitly
    because the trigger is AFTER INSERT: deleting from ``agent_events`` alone
    leaves the rollup claiming sessions that no longer exist.
    """
    await conn.execute("DELETE FROM agent_events WHERE session_id LIKE $1", f"{SESSION_PREFIX}%")
    exists = await conn.fetchval("SELECT to_regclass('agent_event_day_rollup') IS NOT NULL")
    if exists is True:
        await conn.execute(
            "DELETE FROM agent_event_day_rollup WHERE session_id LIKE $1", f"{SESSION_PREFIX}%"
        )


async def _seed_projections() -> tuple[FakeProjectionStore, RepoProjection]:
    """The org structure the scope filters resolve through, built from real events."""
    from syn_domain.contexts.organization.domain.events.RepoAssignedToSystemEvent import (
        RepoAssignedToSystemEvent,
    )
    from syn_domain.contexts.organization.domain.events.RepoRegisteredEvent import (
        RepoRegisteredEvent,
    )

    store = FakeProjectionStore()
    repos = RepoProjection(store=store)
    for repo_id, (full_name, system_id) in _REPOS.items():
        await repos.handle_repo_registered(
            RepoRegisteredEvent(
                repo_id=repo_id,
                organization_id=ORG_ID,
                provider="github",
                provider_repo_id="",
                full_name=full_name,
                owner=full_name.split("/")[0],
                default_branch="main",
                installation_id="",
                is_private=False,
                created_by="test",
            )
        )
        await repos.handle_repo_assigned_to_system(
            RepoAssignedToSystemEvent(repo_id=repo_id, system_id=system_id)
        )

    for execution_id, repo in _CORRELATIONS.items():
        await store.save(
            REPO_CORRELATION,
            execution_id,
            {"execution_id": execution_id, "repo_full_name": repo},
        )
    return store, repos


@pytest.fixture
async def seeded(test_infrastructure: TestInfrastructure) -> AsyncGenerator[SeededHeatmap, None]:
    """Write half the seed through the backfill path and half through the trigger.

    The rollup is dropped and rebuilt per test rather than once per module. The
    backfill test below deletes a rollup row on purpose, and a shared rollup
    would leave every test after it asserting on a table another test edited.
    """
    import asyncpg

    from syn_adapters.events import AgentEventStore
    from syn_adapters.events.schema import EventStoreSchema

    dsn = _utc(test_infrastructure.timescaledb_url)

    store = AgentEventStore(dsn)
    await store.initialize()  # ensure_schema: agent_events, rollup, trigger

    pool = await asyncpg.create_pool(dsn)
    assert pool is not None

    async with pool.acquire() as conn:
        await _forget_seeded_rows(conn)
        await conn.execute("DROP TRIGGER IF EXISTS agent_events_day_rollup ON agent_events")
        await conn.execute("DROP TABLE IF EXISTS agent_event_day_rollup")

    await store.insert_batch(_events_reaching_the_rollup_by_backfill())

    async with pool.acquire() as conn:
        await EventStoreSchema().ensure_schema(conn)  # rebuilds it, and backfills

    await store.insert_batch(_events_reaching_the_rollup_by_trigger())

    projection_store, repo_projection = await _seed_projections()

    try:
        yield SeededHeatmap(
            dsn=dsn, pool=pool, store=projection_store, repo_projection=repo_projection
        )
    finally:
        async with pool.acquire() as conn:
            await _forget_seeded_rows(conn)
        await pool.close()
        await store.close()


def _totals(buckets: list[HeatmapDayBucket]) -> dict[str, float]:
    """Sum each metric across the window."""
    totals = dict.fromkeys(buckets[0].breakdown, 0.0)
    for bucket in buckets:
        for key, value in bucket.breakdown.items():
            totals[key] += value
    return totals


async def _compare_queries(
    seeded: SeededHeatmap, execution_ids: set[str] | None
) -> list[HeatmapDayBucket]:
    """Run both implementations over one scope and assert they agree, day by day."""
    new = await seeded.new().query(WINDOW_START, WINDOW_END, execution_ids)
    old = await seeded.legacy().query(WINDOW_START, WINDOW_END, execution_ids)

    assert [b.date for b in new] == [b.date for b in old]
    for new_day, old_day in zip(new, old, strict=True):
        assert new_day.breakdown == old_day.breakdown, (
            f"{new_day.date}: the rollup says {new_day.breakdown}, "
            f"the pre-#1253 agent_events scan says {old_day.breakdown}"
        )
    return new


class TestOldAndNewAgree:
    """The heatmap's answers, before #1253 and after, over the same rows."""

    async def test_unfiltered_window_agrees_on_every_metric(self, seeded: SeededHeatmap) -> None:
        """No scope filter: the whole window, both implementations.

        The totals below are not decoration. ``{} == {}`` is the failure this
        whole file guards against - two implementations agreeing because
        neither found anything - and every assertion here is a number this
        module seeded rather than a "> 0".
        """
        totals = _totals(await _compare_queries(seeded, None))

        assert totals["sessions"] == float(SEEDED_SESSIONS - 1), (
            "ten sessions were seeded and `pre-edge` started before the "
            f"window, so nine are in it. Got {totals['sessions']}"
        )
        assert totals["commits"] == float(SEEDED_COMMITS)
        assert totals["executions"] > 0
        assert totals["cost_usd"] > 0
        assert totals["tokens"] > 0
        assert totals["input_tokens"] > 0
        assert totals["output_tokens"] > 0

    async def test_a_session_crossing_midnight_is_counted_once(self, seeded: SeededHeatmap) -> None:
        """On its start day, and only there - in both implementations.

        `pre-3` starts at 23:30 on day 2 and keeps emitting on day 3. Its
        EXECUTION appears on both days, because an execution that spans days
        did work on each. The session appears on one.
        """
        buckets = await _compare_queries(seeded, {EXEC_A2})
        by_day = {b.date: b.breakdown for b in buckets}
        day_two = (WINDOW_START + timedelta(days=2)).isoformat()
        day_three = (WINDOW_START + timedelta(days=3)).isoformat()

        assert by_day[day_two]["sessions"] == 1.0
        assert by_day[day_three]["sessions"] == 0.0
        assert by_day[day_two]["executions"] == 1.0
        assert by_day[day_three]["executions"] == 1.0

    async def test_a_session_starting_before_the_window_is_not_counted(
        self, seeded: SeededHeatmap
    ) -> None:
        """...but its commit still lands on the in-window day it happened on.

        This is the one case where "count the sessions in the window" and
        "count the activity in the window" have to give different answers, and
        the new implementation reaches it through an anti-join on the rollup
        instead of on agent_events.
        """
        buckets = await _compare_queries(seeded, {EXEC_A2})
        by_day = {b.date: b.breakdown for b in buckets}
        day_two = (WINDOW_START + timedelta(days=2)).isoformat()

        # ccc1 is pre-3's, on day 3; ddd1 is pre-edge's, on day 2.
        assert by_day[day_two]["commits"] == 1.0
        assert _totals(buckets)["sessions"] == 1.0, "only pre-3 started in the window"

    async def test_each_execution_scope_agrees(self, seeded: SeededHeatmap) -> None:
        """One execution at a time - the narrowest scope the query takes."""
        for execution_id in (EXEC_A1, EXEC_A2, EXEC_B1, EXEC_G1):
            totals = _totals(await _compare_queries(seeded, {execution_id}))
            assert totals["executions"] > 0, execution_id
            assert totals["tokens"] > 0, execution_id

    async def test_a_multi_execution_scope_agrees(self, seeded: SeededHeatmap) -> None:
        """The shape the org/system/repo filters actually produce: a set."""
        totals = _totals(await _compare_queries(seeded, {EXEC_A1, EXEC_A2}))
        assert totals["sessions"] == 5.0, "pre-1, pre-2, pre-3, post-1, post-2"

    async def test_a_summary_after_the_window_still_prices_the_session(
        self, seeded: SeededHeatmap
    ) -> None:
        """`post-tail` ends three days past the window, and is priced from that end.

        If the usage join were bounded by time, this session would be priced
        from its placeholder turn row - 5 output tokens for a session that
        produced 13,300 - and the two implementations would disagree here
        first.
        """
        buckets = await _compare_queries(seeded, {EXEC_B1})
        by_day = {b.date: b.breakdown for b in buckets}
        tail_day = (WINDOW_START + timedelta(days=9)).isoformat()

        assert by_day[tail_day]["output_tokens"] == 13300.0
        assert by_day[tail_day]["cost_usd"] == 1.25


class TestScopeFiltersAgreeThroughTheHandler:
    """org / system / repo, resolved by the production handler, not by the test.

    The handler is what turns each of those into the execution-id set the query
    takes. Driving it, rather than hand-rolling the sets, is what makes "every
    scope filter" mean the scopes a user can actually ask for. Only
    ``_timescale`` is swapped, so repo resolution, the correlation read and the
    empty-filter guard are the same production code on both sides.
    """

    @staticmethod
    async def _compare(seeded: SeededHeatmap, query: GetContributionHeatmapQuery) -> float:
        new_handler = GetContributionHeatmapHandler(
            seeded.pool, seeded.store, seeded.repo_projection
        )
        old_handler = GetContributionHeatmapHandler(
            seeded.pool, seeded.store, seeded.repo_projection
        )
        old_handler._timescale = seeded.legacy()  # type: ignore[assignment]

        new_result = await new_handler.handle(query)
        old_result = await old_handler.handle(query)

        assert [d.date for d in new_result.days] == [d.date for d in old_result.days]
        for new_day, old_day in zip(new_result.days, old_result.days, strict=True):
            assert new_day.breakdown == old_day.breakdown, new_day.date
            assert new_day.count == old_day.count, new_day.date
        assert new_result.total == old_result.total
        assert new_result.filter == old_result.filter
        return new_result.total

    async def test_organization_scope(self, seeded: SeededHeatmap) -> None:
        """Every repo is this org's, so this is the unfiltered set, resolved."""
        total = await self._compare(
            seeded,
            GetContributionHeatmapQuery(
                organization_id=ORG_ID,
                start_date=WINDOW_START,
                end_date=WINDOW_END,
                metric="sessions",
            ),
        )
        assert total == float(SEEDED_SESSIONS - 1)

    async def test_system_scope(self, seeded: SeededHeatmap) -> None:
        """System one holds alpha and beta, so not gamma's execution."""
        total = await self._compare(
            seeded,
            GetContributionHeatmapQuery(
                system_id=SYSTEM_ONE,
                start_date=WINDOW_START,
                end_date=WINDOW_END,
                metric="sessions",
            ),
        )
        assert total == 8.0, "every in-window session except post-4, which is gamma's"

    async def test_repo_scope(self, seeded: SeededHeatmap) -> None:
        """One repo, which is two executions: alpha's A1 and A2."""
        total = await self._compare(
            seeded,
            GetContributionHeatmapQuery(
                repo_id=REPO_ID_ALPHA,
                start_date=WINDOW_START,
                end_date=WINDOW_END,
                metric="sessions",
            ),
        )
        assert total == 5.0

    @pytest.mark.parametrize("metric", sorted(VALID_METRICS))
    async def test_every_metric_agrees_under_a_scope(
        self, seeded: SeededHeatmap, metric: str
    ) -> None:
        """`count` carries the selected metric, so this pins each one in turn."""
        total = await self._compare(
            seeded,
            GetContributionHeatmapQuery(
                system_id=SYSTEM_ONE,
                start_date=WINDOW_START,
                end_date=WINDOW_END,
                metric=metric,
            ),
        )
        assert total > 0, f"{metric} totalled zero, so agreeing about it proves nothing"


class TestTheBackfillIsNotPaidAtEveryStartup:
    """The DB-backed half of #1253's startup-cost fix.

    ``ensure_schema()`` runs at every API start. Re-running the backfill there
    is a GROUP BY over ALL of agent_events inside a transaction holding ACCESS
    EXCLUSIVE on it - ingestion stops for the length of a full scan, on every
    restart, forever.

    ``ON CONFLICT DO NOTHING`` makes a repeat invisible in the data, so the only
    way to observe it from SQL is to remove a row the backfill WOULD restore
    and check that it stays removed. (The other half - that the gate is read
    from the catalogue and that the cheap DDL still re-runs - is
    packages/syn-adapters/tests/events/test_day_rollup_backfill_runs_once.py,
    which is a `unit` test because that is what gates a PR into main.)
    """

    async def test_a_second_ensure_schema_does_not_refill_the_rollup(
        self, seeded: SeededHeatmap
    ) -> None:
        from syn_adapters.events.schema import EventStoreSchema

        async with seeded.pool.acquire() as conn:
            victim = await conn.fetchrow(
                "SELECT day, session_id, execution_id FROM agent_event_day_rollup "
                "WHERE session_id LIKE $1 LIMIT 1",
                f"{SESSION_PREFIX}%",
            )
            assert victim is not None, "nothing was seeded - the fixture did not run"
            await conn.execute(
                "DELETE FROM agent_event_day_rollup "
                "WHERE day = $1 AND session_id = $2 "
                "AND COALESCE(execution_id, '') = COALESCE($3, '')",
                victim["day"],
                victim["session_id"],
                victim["execution_id"],
            )

            await EventStoreSchema().ensure_schema(conn)

            restored = await conn.fetchval(
                "SELECT COUNT(*) FROM agent_event_day_rollup WHERE day = $1 AND session_id = $2",
                victim["day"],
                victim["session_id"],
            )

        assert restored == 0, (
            "the deleted rollup row came back, so ensure_schema() re-ran "
            "ROLLUP_BACKFILL_SQL - a full GROUP BY over agent_events, under "
            "ACCESS EXCLUSIVE, at every API restart"
        )

    async def test_the_trigger_still_fires_after_that_second_call(
        self, seeded: SeededHeatmap
    ) -> None:
        """Skipping the backfill must not have skipped re-attaching the trigger.

        The cheap half of ``_create_day_rollup`` is unconditional on purpose: a
        change to what the trigger fires on has to reach a database that
        already has the old one.
        """
        from syn_adapters.events import AgentEventStore
        from syn_adapters.events.schema import EventStoreSchema

        async with seeded.pool.acquire() as conn:
            await EventStoreSchema().ensure_schema(conn)

        latecomer = _sid("latecomer")
        store = AgentEventStore(seeded.dsn)
        await store.initialize()
        try:
            await store.insert_batch([_commit(latecomer, EXEC_A1, _at(10, 6), "zzz1")])
        finally:
            await store.close()

        async with seeded.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT commits FROM agent_event_day_rollup WHERE session_id = $1", latecomer
            )

        assert row is not None, "the trigger did not fire on a post-restart insert"
        assert row["commits"] == 1


class TestWriteAmplification:
    """What the trigger costs the ingestion hot path, measured rather than guessed.

    The trigger adds an upsert per ``agent_events`` row, on the path every
    event takes. That cost is real, it is paid forever, and #1253 accepted it
    to make the read path bounded - so it is reported here rather than left to
    be discovered in production. The number is printed on every run.

    The assertion is deliberately loose. A tight bound on a shared CI runner
    measures the runner. What is worth failing over is a change of ORDER: an
    upsert that starts seq-scanning because the unique index the ON CONFLICT
    targets was renamed would show up here and nowhere else.
    """

    BATCH = 500

    @staticmethod
    def _batch(session: str, size: int) -> list[SeedEvent]:
        return [_tokens(session, EXEC_A1, _at(10, 3) + timedelta(seconds=i)) for i in range(size)]

    async def test_trigger_overhead_per_insert_is_measured_and_bounded(
        self, seeded: SeededHeatmap, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from syn_adapters.events import AgentEventStore
        from syn_adapters.events.schema import EventStoreSchema

        store = AgentEventStore(seeded.dsn)
        await store.initialize()

        # Warm the pool and the plan cache. Without this the first batch pays
        # connection setup and the measurement reports it as trigger cost.
        await store.insert_batch(self._batch(_sid("amp-warmup"), 20))

        try:
            with_trigger_session = _sid("amp-on")
            started = clock.perf_counter()
            await store.insert_batch(self._batch(with_trigger_session, self.BATCH))
            with_trigger = clock.perf_counter() - started

            async with seeded.pool.acquire() as conn:
                await conn.execute("DROP TRIGGER agent_events_day_rollup ON agent_events")

            without_trigger_session = _sid("amp-off")
            started = clock.perf_counter()
            await store.insert_batch(self._batch(without_trigger_session, self.BATCH))
            without_trigger = clock.perf_counter() - started
        finally:
            # Always put the trigger back: everything after this test in the
            # session would otherwise be reading a rollup nothing maintains.
            async with seeded.pool.acquire() as conn:
                await EventStoreSchema().ensure_schema(conn)
            await store.close()

        per_insert_us = (with_trigger - without_trigger) / self.BATCH * 1_000_000
        with capsys.disabled():
            print(
                f"\n[#1253 write amplification] {self.BATCH} events through COPY: "
                f"trigger on {with_trigger * 1000:.1f}ms, off {without_trigger * 1000:.1f}ms, "
                f"delta {per_insert_us:+.1f}us per event"
            )

        assert with_trigger < max(without_trigger * 20, 0.25), (
            f"the rollup trigger cost {per_insert_us:.1f}us per event "
            f"({with_trigger:.3f}s against {without_trigger:.3f}s for {self.BATCH} rows). "
            "That is an order-of-magnitude change on the ingestion hot path - check "
            "that agent_event_day_rollup_key still matches the ON CONFLICT target."
        )
