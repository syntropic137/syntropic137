"""The rollup gate asks whether the rollup is still being MAINTAINED (#1371).

THREE FINDINGS, ONE STARTUP PATH

``EventStoreSchema._create_day_rollup()`` runs at every API startup, and three
of the review findings on #1253 are about what it does there. They share a
fixture and a database, so they share a file.

  #2 COMPLETENESS. The backfill was gated on the rollup TABLE existing. The
     rollup is kept up to date by a trigger, and a trigger can go without the
     table going with it - ``ALTER TABLE ... DISABLE TRIGGER`` during an
     incident, a restore that drops it, a test. Every event that lands while it
     is gone is missing from the rollup, and startup re-attaches the trigger
     unconditionally, so the gate said "complete" ever after. The heatmap
     under-reported that window permanently, and nothing said so.

  #4 WRITE AMPLIFICATION. The trigger's upsert ran an UPDATE for every event,
     including the overwhelming majority that change neither column: a later
     event on a day already open, of any type but ``git_commit``. Each one wrote
     a new row version to be vacuumed later. The conflict action now carries a
     WHERE, so those events touch nothing.

  #5 CONCURRENT FIRST START. The ``to_regclass`` check was read before the
     advisory lock was taken, so two replicas starting together could both read
     "no rollup" and both scan the whole of agent_events - each one an ingestion
     outage, for a result the other was about to produce.

WHY THESE NEED A REAL DATABASE

Each is a claim about what PostgreSQL DOES, not about what the SQL says:
``tgenabled`` after a DISABLE TRIGGER, a row version that a suppressed upsert
does not create, and two sessions actually queueing on ``pg_advisory_xact_lock``.
The statement-level halves that gate a PR into main are unit tests -
test_day_rollup_startup_gate.py and test_day_rollup_write_amplification.py -
because this file's marker (``integration``) runs only on schedule,
workflow_dispatch, push to main, and PRs into ``release``.

WHAT "CORRECT" MEANS HERE

``_rollup_disagreements()`` recomputes the rollup from ``agent_events`` and
FULL OUTER JOINs it against what is stored, so a row that is missing, extra,
short or stale all show up as disagreements. That is deliberately the same
aggregate the backfill computes - the assertion is not "the backfill ran", it
is "the stored rollup and the events now say the same thing", which is the
property the heatmap actually depends on.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest

from syn_adapters.events.schema import ROLLUP_BACKFILL_SQL, EventStoreSchema
from syn_shared.events import GIT_COMMIT, SESSION_STARTED, TOOL_EXECUTION_STARTED

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    import asyncpg
    from syn_tests.fixtures.infrastructure import TestInfrastructure

pytestmark = pytest.mark.integration


SESSION_PREFIX = "hrec-"
EXECUTION_PREFIX = "hrex-"

TRIGGER = "agent_events_day_rollup"


def _names() -> tuple[str, str]:
    """A fresh session/execution pair, so two tests never share a rollup row."""
    tag = uuid4().hex[:10]
    return f"{SESSION_PREFIX}{tag}", f"{EXECUTION_PREFIX}{tag}"


def _ts(iso: str) -> datetime:
    """An instant, written with its offset so nothing has to infer one."""
    return datetime.fromisoformat(iso)


async def _row_version(conn: asyncpg.Connection, session: str) -> str | None:
    """The transaction that wrote the row currently on disk.

    ``xmin`` is how "did that upsert actually write anything" is asked of
    PostgreSQL rather than of the statement text: it changes if and only if a
    new row version was produced. Cast to text because asyncpg has no codec for
    the ``xid`` type.
    """
    value: str | None = await conn.fetchval(
        "SELECT xmin::text FROM agent_event_day_rollup WHERE session_id = $1", session
    )
    assert value is not None, "no rollup row for this session - the trigger never fired"
    return value


#: Missing, extra, short or stale - all four as one query.
#:
#: The right-hand side is recomputed from agent_events with the same aggregate
#: the backfill uses, so this asks the only question worth asking: do the stored
#: rollup and the events agree? Scoped to this module's prefix because the
#: database is shared and the backfill rebuilds every row in it, including other
#: modules'.
_DISAGREEMENTS_SQL = f"""
WITH truth AS (
    SELECT (time AT TIME ZONE 'UTC')::date AS day,
           session_id,
           execution_id,
           MIN(time) AS first_time,
           COUNT(*) FILTER (WHERE event_type = '{GIT_COMMIT}') AS commits
    FROM agent_events
    WHERE session_id LIKE $1
    GROUP BY 1, 2, 3
),
stored AS (
    SELECT day, session_id, execution_id, first_time, commits
    FROM agent_event_day_rollup
    WHERE session_id LIKE $1
)
SELECT COALESCE(t.session_id, s.session_id) AS session_id,
       COALESCE(t.day, s.day)               AS day,
       t.first_time AS events_say_first_time, s.first_time AS rollup_says_first_time,
       t.commits    AS events_say_commits,    s.commits    AS rollup_says_commits
FROM truth t
FULL OUTER JOIN stored s
  ON s.day = t.day
 AND s.session_id = t.session_id
 AND s.execution_id IS NOT DISTINCT FROM t.execution_id
WHERE t.session_id IS NULL
   OR s.session_id IS NULL
   OR t.first_time <> s.first_time
   OR t.commits <> s.commits
"""


async def _disagreements(conn: asyncpg.Connection) -> list[asyncpg.Record]:
    return list(await conn.fetch(_DISAGREEMENTS_SQL, f"{SESSION_PREFIX}%"))


async def _emit(
    conn: asyncpg.Connection, session: str, execution: str, at: datetime, event_type: str
) -> None:
    """One raw event.

    Raw SQL rather than ``AgentEventStore``: these tests care about the trigger
    firing on an INSERT, and about which connection performs it, neither of
    which is the store's business.
    """
    await conn.execute(
        "INSERT INTO agent_events (time, event_type, session_id, execution_id, data) "
        "VALUES ($1, $2, $3, $4, '{}'::jsonb)",
        at,
        event_type,
        session,
        execution,
    )


async def _forget_seeded_rows(conn: asyncpg.Connection) -> None:
    """Every row this module has written, from both tables.

    Before as well as after: a run killed mid-test leaves events behind, and
    the reconciliation assertions are over everything carrying the prefix.
    """
    await conn.execute("DELETE FROM agent_events WHERE session_id LIKE $1", f"{SESSION_PREFIX}%")
    if await conn.fetchval("SELECT to_regclass('agent_event_day_rollup') IS NOT NULL") is True:
        await conn.execute(
            "DELETE FROM agent_event_day_rollup WHERE session_id LIKE $1", f"{SESSION_PREFIX}%"
        )


@pytest.fixture
async def conn(test_infrastructure: TestInfrastructure) -> AsyncGenerator[asyncpg.Connection, None]:
    """One connection against a schema that already exists and a clean prefix.

    The zone is pinned to UTC so a failure here is about the gate and not about
    #1371's other half - which test_heatmap_day_is_utc.py owns.
    """
    import asyncpg

    from syn_adapters.events import AgentEventStore

    dsn = test_infrastructure.timescaledb_url
    store = AgentEventStore(dsn)
    await store.initialize()
    await store.close()

    connection = await asyncpg.connect(f"{dsn}{'&' if '?' in dsn else '?'}timezone=UTC")
    try:
        await _forget_seeded_rows(connection)
        yield connection
        await _forget_seeded_rows(connection)
    finally:
        await connection.close()


class TestATriggerThatStoppedMaintainingItEarnsABackfill:
    """#2. The table surviving is not evidence that the rollup is current."""

    @pytest.mark.parametrize(
        "how_it_stopped",
        (
            f"DROP TRIGGER {TRIGGER} ON agent_events",
            f"ALTER TABLE agent_events DISABLE TRIGGER {TRIGGER}",
            f"ALTER TABLE agent_events ENABLE REPLICA TRIGGER {TRIGGER}",
        ),
        ids=("dropped", "disabled", "replica-only"),
    )
    async def test_the_gap_is_closed_on_the_next_startup(
        self, conn: asyncpg.Connection, how_it_stopped: str
    ) -> None:
        """Both spellings, because they leave the catalogue in different states.

        DROP removes the ``pg_trigger`` row; DISABLE leaves it with
        ``tgenabled = 'D'``. A gate that asked only "does a trigger row exist"
        would pass the second and leave the gap open, so the disabled case is
        the one that fails if completeness is checked by existence alone.
        """
        session, execution = _names()
        before = "2023-05-11T09:00:00+00:00"
        during = "2023-05-11T10:00:00+00:00"

        await _emit(conn, session, execution, _ts(before), SESSION_STARTED)
        await conn.execute(how_it_stopped)
        await _emit(conn, session, execution, _ts(during), GIT_COMMIT)

        assert await _disagreements(conn), (
            "the events inserted while the trigger was gone were rolled up "
            "anyway, so this test is no longer exercising a gap"
        )

        await EventStoreSchema().ensure_schema(conn)

        assert await _disagreements(conn) == [], (
            "the rollup still disagrees with agent_events after a startup that "
            "found the trigger gone. Nothing else will ever fix it: the trigger "
            "is re-attached but only sees FUTURE events, so the heatmap "
            "under-reports that window permanently (#1371 finding 2)"
        )

    async def test_it_recomputes_rather_than_only_filling_holes(
        self, conn: asyncpg.Connection
    ) -> None:
        """A row can be present and WRONG, which DO NOTHING would not repair.

        The gap the trigger left is not always a missing row - if the day was
        already open, the surviving row is short by the events that arrived
        while the trigger was off. The reconciling backfill assigns
        ``EXCLUDED``, which is a complete aggregate, so a short row is corrected
        the same way a missing one is created.
        """
        session, execution = _names()

        await _emit(conn, session, execution, _ts("2023-05-12T08:00:00+00:00"), GIT_COMMIT)
        await conn.execute(f"ALTER TABLE agent_events DISABLE TRIGGER {TRIGGER}")
        await _emit(conn, session, execution, _ts("2023-05-12T09:00:00+00:00"), GIT_COMMIT)
        await _emit(conn, session, execution, _ts("2023-05-12T07:00:00+00:00"), GIT_COMMIT)

        stale = await conn.fetchrow(
            "SELECT commits FROM agent_event_day_rollup WHERE session_id = $1", session
        )
        assert stale is not None and stale["commits"] == 1, (
            "the day's row should have survived, holding only the one commit "
            "that arrived while the trigger was live"
        )

        await EventStoreSchema().ensure_schema(conn)

        assert await _disagreements(conn) == [], (
            "a row that existed but was SHORT was left alone. An upsert that "
            "does nothing on conflict cannot repair one - the backfill has to "
            "recompute (#1371 finding 2)"
        )

    async def test_the_healthy_restart_still_runs_no_backfill(
        self, conn: asyncpg.Connection
    ) -> None:
        """The whole point of the gate, asserted by what a backfill WOULD do.

        Counting statements would prove it too, but only against this
        implementation. A value that only a full scan could correct is a claim
        about effect: plant one, restart, and if it survives then nothing
        recomputed the row. #1253 exists because that scan is an ingestion
        outage on every restart.
        """
        session, execution = _names()
        await _emit(conn, session, execution, _ts("2023-05-13T08:00:00+00:00"), SESSION_STARTED)

        await conn.execute(
            "UPDATE agent_event_day_rollup SET commits = 99 WHERE session_id = $1", session
        )

        await EventStoreSchema().ensure_schema(conn)

        assert (
            await conn.fetchval(
                "SELECT commits FROM agent_event_day_rollup WHERE session_id = $1", session
            )
            == 99
        ), (
            "a healthy restart recomputed the rollup. That is a GROUP BY over "
            "all of agent_events, holding SHARE ROW EXCLUSIVE on it, on every "
            "API start - the outage #1253 was opened to remove"
        )


class TestAnEventThatChangesNothingWritesNothing:
    """#4. The suppressed upsert, measured as row versions rather than as SQL."""

    async def test_a_later_non_commit_event_leaves_the_row_untouched(
        self, conn: asyncpg.Connection
    ) -> None:
        """The common case by a wide margin, and it used to cost an UPDATE.

        ``xmin`` is the transaction that produced the row version on disk, so
        it moves if and only if the upsert actually updated. Most events are
        neither the day's first nor a commit: they can move neither column, and
        now they write nothing to vacuum later.
        """
        session, execution = _names()
        await _emit(conn, session, execution, _ts("2023-05-14T08:00:00+00:00"), SESSION_STARTED)
        untouched = await _row_version(conn, session)

        await _emit(
            conn, session, execution, _ts("2023-05-14T09:00:00+00:00"), TOOL_EXECUTION_STARTED
        )

        assert await _row_version(conn, session) == untouched, (
            "a later, non-commit event rewrote the rollup row. It can change "
            "neither first_time nor commits, so every one of them was a dead "
            "row version for vacuum to collect (#1371 finding 4)"
        )

    async def test_an_earlier_event_still_moves_first_time(self, conn: asyncpg.Connection) -> None:
        """Suppression must not cost correctness: `<`, not `<=`, not nothing.

        Events do arrive out of order - a collector retry, a batch import - and
        the day's ``first_time`` is what the heatmap calls the session start.
        """
        session, execution = _names()
        await _emit(conn, session, execution, _ts("2023-05-15T08:00:00+00:00"), SESSION_STARTED)
        before = await _row_version(conn, session)

        await _emit(
            conn, session, execution, _ts("2023-05-15T06:00:00+00:00"), TOOL_EXECUTION_STARTED
        )

        assert await _row_version(conn, session) != before, "the earlier event was suppressed"
        assert await _disagreements(conn) == [], "first_time did not move to the earlier event"

    async def test_a_commit_still_counts(self, conn: asyncpg.Connection) -> None:
        """The other half of the WHERE, and the one the heatmap displays."""
        session, execution = _names()
        await _emit(conn, session, execution, _ts("2023-05-16T08:00:00+00:00"), SESSION_STARTED)
        before = await _row_version(conn, session)

        await _emit(conn, session, execution, _ts("2023-05-16T09:00:00+00:00"), GIT_COMMIT)

        assert await _row_version(conn, session) != before, (
            "a git_commit that arrived after the day was open was suppressed - "
            "the commits column can only ever be incremented by exactly these "
            "events, so suppressing one loses it for good"
        )
        assert await _disagreements(conn) == [], "the commit was not counted"


class _BackfillCountingConnection:
    """A real connection that also says whether the backfill went through it.

    Everything is delegated; only ``execute`` is watched. Wrapping real
    connections rather than faking them is the point of the test - two fakes
    cannot queue on an advisory lock, and queueing is the behaviour under test.
    """

    def __init__(self, conn: asyncpg.Connection) -> None:
        self._conn = conn
        self.backfills = 0

    async def execute(self, query: str, *args: object, **kwargs: object) -> object:
        if query == ROLLUP_BACKFILL_SQL:
            self.backfills += 1
        return await self._conn.execute(query, *args, **kwargs)

    def __getattr__(self, name: str) -> object:
        return getattr(self._conn, name)


class TestTwoFirstStartsPayTheBackfillOnce:
    """#5. The lock is taken before the question is asked, so there is no race."""

    async def test_only_one_of_them_scans(
        self, conn: asyncpg.Connection, test_infrastructure: TestInfrastructure
    ) -> None:
        """Two replicas starting together against an absent rollup.

        With the read before the lock, both see "no rollup" and both scan all
        of agent_events - two ingestion outages for one result. With the lock
        first, the loser wakes after the winner has COMMITTED and sees a
        finished rollup, so it backfills nothing.

        The assertion is `== 1` and not `<= 1`: zero would mean the rollup was
        never absent and the race was never set up.
        """
        import asyncpg

        session, execution = _names()
        await _emit(conn, session, execution, _ts("2023-05-17T08:00:00+00:00"), GIT_COMMIT)

        await conn.execute(f"DROP TRIGGER IF EXISTS {TRIGGER} ON agent_events")
        await conn.execute("DROP TABLE IF EXISTS agent_event_day_rollup")

        dsn = test_infrastructure.timescaledb_url
        replicas = [await asyncpg.connect(dsn) for _ in range(2)]
        watched = [_BackfillCountingConnection(replica) for replica in replicas]
        try:
            await asyncio.gather(
                *(
                    EventStoreSchema().ensure_schema(watched[0]),
                    EventStoreSchema().ensure_schema(watched[1]),
                )  # type: ignore[arg-type]
            )
        finally:
            for replica in replicas:
                await replica.close()

        assert sum(w.backfills for w in watched) == 1, (
            "concurrent first startups ran "
            f"{sum(w.backfills for w in watched)} backfills. Each one is a "
            "GROUP BY over the whole of agent_events under a lock that blocks "
            "ingestion, and every one after the first produces a result that "
            "already exists (#1371 finding 5)"
        )
        assert await _disagreements(conn) == [], "the one backfill that ran was not enough"
