"""What startup decides about the rollup, and what it decides it under (#1371).

TWO FINDINGS, ONE DECISION

``_create_day_rollup`` has exactly one thing to work out: may it skip the
full-table backfill? Both findings below are that decision going wrong.

  the question was too weak     It asked whether the TABLE existed. The table
                                is not what keeps the rollup current - the
                                trigger is. Drop or disable that trigger and
                                the table stays exactly where it was while
                                every arriving event goes unrecorded. Startup
                                then re-attaches the trigger, sees a table, and
                                skips reconciliation, so the events that
                                arrived in the gap are missing FOREVER: nothing
                                ever recomputes them, and the heatmap
                                under-reports that window with no sign that it
                                is doing so.

  it was asked without a lock   Two replicas booting together could both read
                                "no rollup" before either committed, and both
                                would scan the whole of agent_events. Each scan
                                blocks ingestion. ``pg_advisory_xact_lock``
                                taken BEFORE the read makes the loser wait and
                                then see a finished rollup.

WHY THESE ARE UNIT TESTS

They are assertions about a decision, and the decision is made in Python from
two catalogue answers. The fake below answers those from the DDL the code
actually executed, so a startup that never creates the trigger cannot pass by
telling the fake what it wants to hear.

What they cannot reach is whether PostgreSQL agrees: that ``tgenabled <> 'D'``
really is how a disabled trigger reads, that the recomputing upsert really does
repair a short row, that two real connections really do serialise on the lock.
Those are ``test_day_rollup_reconciliation.py``, marked ``integration``,
which does not run on a PR into ``main`` (ci.yml). ``pytest -m unit`` is what
gates the PR, so the decision itself is pinned here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from syn_adapters.events.schema import (
    ROLLUP_BACKFILL_SQL,
    EventStoreSchema,
)

from .test_day_rollup_backfill_runs_once import CatalogueConnection

if TYPE_CHECKING:
    from collections.abc import Callable

# CI runs `pytest -m unit`; an unmarked module collects zero tests and the
# gate goes green having run none of them (#1065).
pytestmark = pytest.mark.unit


TRIGGER = "agent_events_day_rollup"

_ADVISORY_LOCK = "SELECT pg_advisory_xact_lock($1)"


class _OrderedConnection(CatalogueConnection):
    """CatalogueConnection whose ``calls`` also carry the transaction boundary.

    The claim under test is about ORDER - the lock before the first read, both
    inside one transaction - so the transaction has to appear in the same
    sequence as the statements rather than wrapping them invisibly.
    """

    BEGIN = "-- BEGIN"
    COMMIT = "-- COMMIT"

    def transaction(self) -> _OrderedConnection:
        return self

    async def __aenter__(self) -> _OrderedConnection:
        self.calls.append(self.BEGIN)
        return self

    async def __aexit__(self, *_: object) -> bool:
        self.calls.append(self.COMMIT)
        return False


async def _startup(conn: CatalogueConnection, schema: EventStoreSchema) -> None:
    await schema.ensure_schema(conn)  # type: ignore[arg-type]


class TestATableIsNotProofTheRollupIsComplete:
    """The finding: existence answered a question nobody had asked."""

    @pytest.mark.parametrize(
        "stop_it",
        (CatalogueConnection.drop_trigger, CatalogueConnection.disable_trigger),
        ids=("dropped", "disabled"),
    )
    async def test_a_trigger_that_stopped_maintaining_it_earns_a_backfill(
        self, stop_it: Callable[[CatalogueConnection, str], None]
    ) -> None:
        """The gap-closing case, and the one the old gate got wrong.

        The table survives - nothing dropped it - so the old gate saw it, said
        "filled", and skipped. Every event that arrived while the trigger was
        detached stayed missing.

        Both ways of stopping a trigger, because PostgreSQL leaves the
        catalogue in different states for them: DROP removes the pg_trigger
        row, DISABLE leaves it with ``tgenabled = 'D'``. A live-check written
        as "does a trigger row exist" passes the disabled case and leaves the
        gap open forever, so that case has to be asked separately.
        """
        conn = _OrderedConnection()
        schema = EventStoreSchema()

        await _startup(conn, schema)
        stop_it(conn, TRIGGER)
        await _startup(conn, schema)

        assert conn.count_backfills() == 2, (
            "the rollup's trigger was gone and startup skipped reconciliation "
            "anyway. The table existing says nothing about whether anything "
            "kept it current (#1371)."
        )

    async def test_the_healthy_restart_still_issues_no_backfill(self) -> None:
        """The boundary, and the reason the old gate existed at all.

        A gate that fires on every restart is not a stricter gate, it is the
        outage the gate was added to stop: a GROUP BY over all of agent_events,
        under a lock that conflicts with INSERT, at every boot.

        It also pins the ORDERING trap in the fix. The completeness check has
        to run before ``DROP TRIGGER IF EXISTS`` further down the same
        function. Read it after, and the trigger is always missing, and every
        startup looks like the broken one above.
        """
        conn = _OrderedConnection()
        schema = EventStoreSchema()

        await _startup(conn, schema)
        await _startup(conn, schema)
        await _startup(conn, schema)

        assert conn.count_backfills() == 1

    async def test_the_table_going_missing_still_earns_one(self) -> None:
        """Widening the question must not have narrowed it.

        The original half is still a half: a rolled-back CREATE TABLE leaves no
        table, and no table means nothing was filled.
        """
        conn = _OrderedConnection()
        schema = EventStoreSchema()

        await _startup(conn, schema)
        conn.forget_relation("agent_event_day_rollup")
        await _startup(conn, schema)

        assert conn.count_backfills() == 2


class TestTheBackfillCanActuallyRepair:
    """Firing the gate buys nothing if the statement it fires cannot fix anything."""

    def test_it_recomputes_the_row_rather_than_leaving_the_stale_one(self) -> None:
        """``DO NOTHING`` would make the whole of the fix above a no-op.

        The rows a detached trigger left behind EXIST - they are just short by
        the events that arrived in the gap. A backfill that skips on conflict
        would walk past every one of them, and the reconciliation would report
        success having repaired nothing.

        Overwriting is sound because the SELECT is a complete aggregate over
        all of agent_events: EXCLUDED is the whole truth for the triple, not a
        delta, so assigning it converges instead of accumulating.
        """
        assert "DO NOTHING" not in ROLLUP_BACKFILL_SQL, (
            "the reconciling backfill skips rows that already exist, which is "
            "exactly the set of rows a detached trigger left short"
        )
        assert "DO UPDATE" in ROLLUP_BACKFILL_SQL
        # Whitespace collapsed: the statement aligns its `=` for readability,
        # and that alignment is not part of the claim.
        assignments = " ".join(ROLLUP_BACKFILL_SQL.split())
        for column in ("first_time", "commits"):
            assert f"{column} = EXCLUDED.{column}" in assignments


class TestTheDecisionIsMadeUnderALock:
    """So two replicas booting together pay the scan at most once."""

    async def test_the_lock_is_taken_before_anything_is_read(self) -> None:
        """Taking it after the read would serialise nothing.

        The race is between the READ and the COMMIT: both replicas see no
        rollup, then both back-fill. A lock acquired after either replica has
        already decided comes too late to change what it decided.
        """
        conn = _OrderedConnection()

        await _startup(conn, EventStoreSchema())

        lock = conn.calls.index(_ADVISORY_LOCK)
        first_read = next(i for i, sql in enumerate(conn.calls) if "to_regclass" in sql)

        assert lock < first_read, (
            "the rollup's advisory lock is taken after startup has already "
            "read whether the rollup exists, so two replicas can both read "
            "'no' and both run the full backfill (#1371)"
        )

    async def test_it_is_transaction_scoped_and_inside_the_transaction(self) -> None:
        """``pg_advisory_xact_lock`` and not ``pg_advisory_lock``.

        Transaction-scoped is what makes the release automatic and exact: it
        goes at COMMIT, which is the same instant the rollup becomes visible to
        the replica waiting on it. A session-level lock would have to be
        released by hand, and an exception on the way out would hold it until
        the connection died - deadlocking every other replica's startup.

        Taken inside the transaction for the same reason: outside it, the lock
        would be released before the DDL it protects had committed.
        """
        conn = _OrderedConnection()

        await _startup(conn, EventStoreSchema())

        begin = conn.calls.index(_OrderedConnection.BEGIN)
        commit = conn.calls.index(_OrderedConnection.COMMIT)
        lock = conn.calls.index(_ADVISORY_LOCK)

        assert begin < lock < commit
        assert "pg_advisory_lock" not in "".join(conn.calls)
