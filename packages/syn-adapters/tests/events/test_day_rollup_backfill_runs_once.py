"""The heatmap rollup's backfill is paid once, not at every API startup.

WHY THIS TEST EXISTS

`EventStoreSchema.ensure_schema()` runs on EVERY API startup. `ROLLUP_BACKFILL_SQL`
is a GROUP BY over ALL of agent_events - it decompresses every chunk, and it
grows with the data - and it runs inside a transaction that has taken SHARE ROW
EXCLUSIVE on agent_events for the CREATE TRIGGER. Run unconditionally, every
restart blocks all event ingestion for the length of a full scan.

The defect is invisible to a correctness test: the backfill recomputes each row
from the raw events, so the DATA is identical either way. The only observable
difference is whether the statement was issued. So this test watches the
statements.

The OTHER half of the gate - that a rollup whose trigger went missing is NOT
treated as complete - is in test_day_rollup_reconciles_a_dead_trigger.py, which
uses the same fake.

It is a unit test on purpose. The integration job that would exercise the real
trigger does not run on pull requests into `main` (see .github/workflows/ci.yml:
schedule, workflow_dispatch, push to main, or a PR into `release`), so a
regression here would reach main ungated. `pytest -m unit` is what gates the PR,
and this is the shape of proof that fits in it. The DB-backed half - delete a
rollup row, re-run ensure_schema, prove it does not come back - lives in
test_heatmap_rollup_equivalence.py.
"""

from __future__ import annotations

import re

import pytest

from syn_adapters.events.schema import (
    ROLLUP_BACKFILL_SQL,
    EventStoreSchema,
)

# CI runs `pytest -m unit`; an unmarked module collects zero tests and the
# gate goes green having run none of them (#1065).
pytestmark = pytest.mark.unit


_VALID_AGENT_EVENTS_SCHEMA = [
    {"column_name": "time", "data_type": "timestamp with time zone"},
    {"column_name": "event_type", "data_type": "text"},
    {"column_name": "session_id", "data_type": "text"},
    {"column_name": "execution_id", "data_type": "text"},
    {"column_name": "phase_id", "data_type": "text"},
    {"column_name": "data", "data_type": "jsonb"},
]


class _NoOpTransaction:
    """asyncpg's `async with conn.transaction():`, with nothing to roll back."""

    async def __aenter__(self) -> _NoOpTransaction:
        return self

    async def __aexit__(self, *_: object) -> bool:
        return False


class CatalogueConnection:
    """A connection that remembers which tables the DDL it was given created.

    Public, rather than underscored, because test_day_rollup_key.py asks the
    same connection a different question: not "was the backfill issued twice"
    but "does the key statement still reach a database that already has the
    table". Both need the catalogue answered from the DDL actually executed.

    The point is that `to_regclass(...) IS NULL` is ANSWERED FROM THE DDL THIS
    CONNECTION ACTUALLY EXECUTED, not from a hardcoded True-then-False. A stub
    that just returned the expected answers would pass even if ensure_schema()
    never created the table, which is the failure mode - "the gate is asked a
    question nobody is answering honestly" - that this whole test is about.
    """

    def __init__(self) -> None:
        self.executed: list[str] = []
        #: Every statement in the order it was sent, asked and issued alike.
        #: `executed` cannot serve: half the gate's decisions are fetchvals, and
        #: the property that the advisory lock is taken BEFORE the first read
        #: is a fact about the two interleaved.
        self.calls: list[str] = []
        self._relations: set[str] = set()
        self._enabled_triggers: set[str] = set()

    async def execute(self, sql: str, *_args: object) -> None:
        self.executed.append(sql)
        self.calls.append(sql)
        created = re.search(r"CREATE TABLE IF NOT EXISTS (\w+)", sql)
        if created:
            self._relations.add(created.group(1))
        # Triggers are tracked the same way and for the same reason: the gate
        # now asks whether one is attached and enabled, and answering that from
        # anywhere but the DDL executed would let a startup that never creates
        # the trigger still look healthy.
        attached = re.search(r"CREATE TRIGGER (\w+)", sql)
        if attached:
            self._enabled_triggers.add(attached.group(1))
        detached = re.search(r"DROP TRIGGER IF EXISTS (\w+)", sql)
        if detached:
            self._enabled_triggers.discard(detached.group(1))

    async def fetchval(self, sql: str, *_args: object) -> bool:
        self.calls.append(sql)
        relation = re.search(r"to_regclass\('(\w+)'\) IS NOT NULL", sql)
        if relation is not None:
            return relation.group(1) in self._relations
        trigger = re.search(r"FROM pg_trigger\b.*?tgname = '(\w+)'", sql, re.DOTALL)
        if trigger is not None:
            return trigger.group(1) in self._enabled_triggers
        msg = f"unexpected fetchval in ensure_schema(): {sql!r}"
        raise AssertionError(msg)

    async def fetch(self, _sql: str, *_args: object) -> list[dict[str, str]]:
        return _VALID_AGENT_EVENTS_SCHEMA

    def transaction(self) -> _NoOpTransaction:
        return _NoOpTransaction()

    def count_backfills(self) -> int:
        return self.executed.count(ROLLUP_BACKFILL_SQL)

    def forget_relation(self, name: str) -> None:
        """Make the catalogue report a table as gone, as a rollback would."""
        self._relations.discard(name)

    def forget_trigger(self, name: str) -> None:
        """Make the catalogue report a trigger as dropped or disabled.

        One method for both, because `_rollup_is_complete()` asks one question -
        "is something still maintaining this table" - and a dropped trigger and
        a disabled one are the same answer to it. Whether PostgreSQL spells the
        difference as an absent pg_trigger row or as `tgenabled = 'D'` is the
        real database's business, and the real database is what
        test_heatmap_rollup_reconciliation.py asks.
        """
        self._enabled_triggers.discard(name)


def _trigger_statements(conn: CatalogueConnection) -> list[str]:
    return [s for s in conn.executed if "agent_events_day_rollup" in s]


class TestDayRollupBackfillRunsOnce:
    async def test_first_startup_backfills(self) -> None:
        """A database that has never seen the rollup gets the full backfill."""
        conn = CatalogueConnection()

        await EventStoreSchema().ensure_schema(conn)  # type: ignore[arg-type]

        assert conn.count_backfills() == 1

    async def test_second_startup_does_not_backfill_again(self) -> None:
        """The restart case: the rollup exists, so the full scan is skipped.

        This is the assertion the fix exists for. Before it, the count was 2 -
        and 3, and 4, once per restart, forever.
        """
        conn = CatalogueConnection()
        schema = EventStoreSchema()

        await schema.ensure_schema(conn)  # type: ignore[arg-type]
        after_first = conn.count_backfills()
        await schema.ensure_schema(conn)  # type: ignore[arg-type]

        assert after_first == 1
        assert conn.count_backfills() == 1, (
            "ROLLUP_BACKFILL_SQL was issued again on the second ensure_schema(). "
            "That is a full GROUP BY over agent_events under ACCESS EXCLUSIVE, "
            "blocking ingestion, on every API restart."
        )

    async def test_second_startup_still_reattaches_the_trigger(self) -> None:
        """Only the backfill is skipped - the cheap DDL still runs.

        Pins the boundary of the gate. A 'fix' that skipped the whole of
        _create_day_rollup on later startups would also pass the test above,
        and would silently strand a database on an old trigger definition.
        """
        conn = CatalogueConnection()
        schema = EventStoreSchema()

        await schema.ensure_schema(conn)  # type: ignore[arg-type]
        first_pass = len(_trigger_statements(conn))
        await schema.ensure_schema(conn)  # type: ignore[arg-type]

        assert first_pass > 0
        assert len(_trigger_statements(conn)) == 2 * first_pass

    async def test_a_dropped_rollup_table_is_rebuilt_and_refilled(self) -> None:
        """The gate keys on the table, so losing the table re-earns the backfill.

        Not a hypothetical: it is the abort path. The backfill runs inside the
        transaction that creates the table, so a failure rolls both back
        together and the table's absence is what tells the next startup the
        rollup was never filled.
        """
        conn = CatalogueConnection()
        schema = EventStoreSchema()

        await schema.ensure_schema(conn)  # type: ignore[arg-type]
        conn.forget_relation("agent_event_day_rollup")
        await schema.ensure_schema(conn)  # type: ignore[arg-type]

        assert conn.count_backfills() == 2
