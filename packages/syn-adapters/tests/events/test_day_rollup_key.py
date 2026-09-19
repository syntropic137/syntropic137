"""The heatmap rollup's key separates a NULL execution_id from an empty one (#1371).

WHAT WENT WRONG

``agent_event_day_rollup`` is keyed on the triple the heatmap counts:
(day, session, execution). ``execution_id`` is nullable, so the key has to say
what two NULLs mean, and it said it with an expression -
``COALESCE(execution_id, '')``. That answers "NULL groups with NULL", which was
the intent, but it also answers "NULL groups with the empty string", which was
not: both map to ``''``, so a row for an unattributed event and a row for an
execution genuinely identified as ``''`` became ONE row. The heatmap's
``COUNT(DISTINCT execution_id)`` for that day then reports whichever of the two
values happened to win the insert, and the other is gone.

WHY THIS ONE IS A UNIT TEST

The DB-backed proof - seed both, get two rollup rows, get the right per-day
execution count - is in
packages/syn-domain/tests/.../contribution_heatmap/test_heatmap_rollup_equivalence.py.
It needs PostgreSQL, and that job does not run on a pull request into ``main``
(ci.yml: schedule, workflow_dispatch, push to main, or a PR into ``release``),
so on its own it would let a regression reach main ungated. ``pytest -m unit``
is what gates the PR, and what fits in it is the statements ``ensure_schema()``
issues. That is enough to hold four things a future edit could break, each of
which is a separate way to reintroduce #1371.
"""

from __future__ import annotations

import pytest

from syn_adapters.events.schema import (
    ROLLUP_BACKFILL_SQL,
    ROLLUP_KEY_SQL,
    ROLLUP_TRIGGER_FUNCTION_SQL,
    EventStoreSchema,
)

from .test_day_rollup_backfill_runs_once import CatalogueConnection

# CI runs `pytest -m unit`; an unmarked module collects zero tests and the
# gate goes green having run none of them (#1065).
pytestmark = pytest.mark.unit


KEY_NAME = "agent_event_day_rollup_key"

#: What the arbiter of both upserts must be. Spelled once here so a test that
#: reads it is comparing against a stated intent rather than against the source
#: it is checking.
THE_KEY = "UNIQUE NULLS NOT DISTINCT (day, session_id, execution_id)"

#: The one form of ON CONFLICT that cannot resolve to some other index.
THE_ARBITER = f"ON CONFLICT ON CONSTRAINT {KEY_NAME}"

#: Every statement in this feature that mentions the rollup's grain.
ROLLUP_SQL = (ROLLUP_KEY_SQL, ROLLUP_TRIGGER_FUNCTION_SQL, ROLLUP_BACKFILL_SQL)


class _TransactionRecordingConnection(CatalogueConnection):
    """CatalogueConnection that also records where the transaction opens and shuts.

    ``_create_day_rollup`` re-keys the rollup and re-attaches the trigger, and
    the claim that the re-key is safe on a live system rests on those two
    happening in ONE transaction - see ``ROLLUP_KEY_SQL``'s comment. That is a
    property of statement ORDER relative to the transaction, so the fake has to
    record the transaction as an event in the same sequence.
    """

    BEGIN = "-- BEGIN"
    COMMIT = "-- COMMIT"

    def transaction(self) -> _TransactionRecordingConnection:
        return self

    async def __aenter__(self) -> _TransactionRecordingConnection:
        self.executed.append(self.BEGIN)
        return self

    async def __aexit__(self, *_: object) -> bool:
        self.executed.append(self.COMMIT)
        return False


async def _startup(conn: CatalogueConnection, schema: EventStoreSchema | None = None) -> None:
    await (schema or EventStoreSchema()).ensure_schema(conn)  # type: ignore[arg-type]


class TestTheKeyDistinguishesNullFromEmptyString:
    """The defect itself: what the rollup is keyed on, and what reads that key."""

    def test_the_key_is_on_the_column_and_says_what_two_nulls_mean(self) -> None:
        """Not on an expression - an expression is how #1371 happened.

        ``NULLS NOT DISTINCT`` buys "NULL groups with NULL" from the column
        itself. Any expression that maps NULL onto a storable value also maps
        that value onto NULL, and merges rows that name different things.
        """
        assert THE_KEY in ROLLUP_KEY_SQL

    @pytest.mark.parametrize("sql", ROLLUP_SQL, ids=("key", "trigger", "backfill"))
    def test_no_rollup_statement_collapses_execution_id_onto_another_value(self, sql: str) -> None:
        """#1371 in one assertion, wherever it is reintroduced.

        The bug needed the same expression in three places to work, and would
        need it again in any ONE of them to come back: a COALESCE in the key
        merges the rows, and a COALESCE in either ON CONFLICT no longer names
        the key at all.
        """
        assert "COALESCE" not in sql.upper(), (
            "a rollup statement is mapping execution_id onto another value. "
            "That is #1371: NULL and '' land in one row and the heatmap's "
            "per-day execution count loses whichever one did not win."
        )

    @pytest.mark.parametrize(
        "sql", (ROLLUP_TRIGGER_FUNCTION_SQL, ROLLUP_BACKFILL_SQL), ids=("trigger", "backfill")
    )
    def test_both_upserts_name_the_key_instead_of_inferring_one(self, sql: str) -> None:
        """``ON CONFLICT (cols)`` infers an arbiter index, and inference matches
        on columns: it cannot ask for the NULLS NOT DISTINCT one. Naming the
        constraint is the only spelling that is exact, and it fails loudly
        rather than quietly choosing a different index.
        """
        assert THE_ARBITER in sql
        assert KEY_NAME in ROLLUP_KEY_SQL, "the upserts name a key nothing declares"


class TestAnExistingDeploymentIsReKeyed:
    """A database created before #1371 holds the COALESCE index. It must lose it."""

    def test_the_old_key_is_dropped_before_the_new_one_is_added(self) -> None:
        """Adding beside it would leave the defect in place.

        The old object enforces the collapse whatever the new key says, so
        "add the right one" is not a fix unless the wrong one goes. It is
        dropped under both spellings it could have - index or constraint -
        because which one a database holds depends on when it was created.
        """
        drops = (f"DROP CONSTRAINT IF EXISTS {KEY_NAME}", f"DROP INDEX IF EXISTS {KEY_NAME}")
        for drop in drops:
            assert drop in ROLLUP_KEY_SQL, (
                f"the replacement never issues `{drop}`, so a database holding "
                "the old key under that spelling keeps it - and keeps #1371 "
                "with it, whatever the new key says"
            )

        add = ROLLUP_KEY_SQL.index("ADD CONSTRAINT")
        drop_constraint, drop_index = (ROLLUP_KEY_SQL.index(drop) for drop in drops)

        assert drop_constraint < drop_index < add, (
            "the replacement must drop the old key before adding the new one, "
            "and drop the constraint spelling first so DROP INDEX is not asked "
            "to remove an index a constraint owns"
        )

    def test_a_database_that_already_has_the_key_is_not_re_keyed(self) -> None:
        """ADD CONSTRAINT has no IF NOT EXISTS and this runs at every API startup.

        Unguarded, every restart would rebuild the index under a lock the
        ingestion trigger needs. The guard asks for the key we want - unique,
        this name, nulls not distinct - rather than for the name alone, so a
        database holding the old expression index does NOT satisfy it and is
        re-keyed, while one already correct is left alone.
        """
        assert "indnullsnotdistinct" in ROLLUP_KEY_SQL
        assert "RETURN;" in ROLLUP_KEY_SQL

    async def test_the_key_statement_runs_on_a_startup_that_skips_the_backfill(self) -> None:
        """The restart case IS the upgrade case, and it is the one that matters.

        Every database that needs re-keying already has the rollup table, so it
        takes the branch that skips the backfill. A re-key placed inside that
        branch would run only where it was never needed, and no existing
        deployment would ever be fixed.
        """
        conn = _TransactionRecordingConnection()
        schema = EventStoreSchema()

        await _startup(conn, schema)
        await _startup(conn, schema)

        assert conn.count_backfills() == 1, "the second startup was not the restart case"
        assert conn.executed.count(ROLLUP_KEY_SQL) == 2, (
            "the second startup did not issue the key statement. Every database "
            "that still holds the COALESCE key already has the rollup table, so "
            "it takes exactly this path - a re-key that only runs when the table "
            "is created reaches nothing that needs it"
        )


class TestTheReKeyIsSafeWhileTheTriggerIsLive:
    async def test_it_shares_the_transaction_that_reattaches_the_trigger(self) -> None:
        """So there is no instant in which the rollup has no key.

        Between dropping the old key and adding the new one the table is
        unconstrained, and the trigger's upsert has no arbiter to name - a
        concurrent insert there would either duplicate a row or fail the whole
        ingesting transaction. Inside the transaction that re-attaches the
        trigger, that insert blocks on SHARE ROW EXCLUSIVE instead and resumes
        against the finished key.
        """
        conn = _TransactionRecordingConnection()

        await _startup(conn)

        executed = conn.executed
        begin = executed.index(_TransactionRecordingConnection.BEGIN)
        commit = executed.index(_TransactionRecordingConnection.COMMIT)
        re_key = executed.index(ROLLUP_KEY_SQL)
        create_trigger = next(
            i for i, sql in enumerate(executed) if "CREATE TRIGGER agent_events_day_rollup" in sql
        )

        assert begin < re_key < commit, "the re-key runs outside the rollup transaction"
        assert begin < create_trigger < commit
