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
treated as complete - is in test_day_rollup_startup_gate.py, which uses the
same fake.

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


#: `pg_trigger.tgenabled`, as PostgreSQL spells it: 'O' for a trigger that
#: fires on origin, 'D' for one that DISABLE TRIGGER stopped. The fake holds
#: the catalogue's own character rather than a boolean so that the predicate a
#: statement writes over that column can be EVALUATED. Recognising the column
#: is not enough - a fake that only noticed `tgenabled` was mentioned accepted
#: `tgenabled = tgenabled`, and the disabled case passed over a tautology
#: (#1371, found in verification).
_TGENABLED_ORIGIN = "O"
_TGENABLED_DISABLED = "D"

#: One comparison against `tgenabled`: an operator and either a quoted literal
#: or a bare column reference. The second alternative is what makes a tautology
#: evaluable rather than unparseable - `tgenabled = tgenabled` is valid SQL and
#: the fake has to answer it the way PostgreSQL would, with True, so the test
#: relying on it goes red.
_TGENABLED_COMPARISON = re.compile(r"tgenabled\s*(=|<>|!=)\s*('[^']*'|\w+)")


def _tgenabled_predicate_holds(sql: str, tgenabled: str) -> bool:
    """Evaluate the statement's own conditions on `tgenabled` against a row.

    Every comparison the SQL writes is evaluated and the results ANDed, which
    is the only shape `ROLLUP_TRIGGER_LIVE_SQL` has ever had. A statement that
    names the column in some form this cannot evaluate raises instead of
    defaulting to satisfied: an unreadable predicate that reads as True is the
    same silent pass this evaluator replaced.
    """
    if "tgenabled" not in sql:
        # Existence alone. Answered as existence alone - which is the bug the
        # disabled case exists to catch, so it must not be papered over here.
        return True
    comparisons = _TGENABLED_COMPARISON.findall(sql)
    if not comparisons:
        msg = f"cannot evaluate this fake's tgenabled condition in: {sql!r}"
        raise AssertionError(msg)
    for operator, operand in comparisons:
        if operand.startswith("'"):
            value = operand[1:-1]
        elif operand == "tgenabled":
            value = tgenabled
        else:
            msg = f"unknown operand {operand!r} compared to tgenabled in: {sql!r}"
            raise AssertionError(msg)
        holds = tgenabled == value if operator == "=" else tgenabled != value
        if not holds:
            return False
    return True


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
        #: The trigger catalogue, keyed the way `pg_trigger` is: a name is
        #: present because a row is attached, and its value is the `tgenabled`
        #: character that row carries. Attached and enabled are held apart
        #: because PostgreSQL spells them apart - an absent row versus one with
        #: `tgenabled = 'D'` - and a live-check that forgets the second half
        #: passes a disabled trigger as healthy. Storing the character, and not
        #: a "disabled" flag, is what lets the SQL's own predicate be run
        #: against it instead of merely recognised.
        self._triggers: dict[str, str] = {}

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
            self._triggers[attached.group(1)] = _TGENABLED_ORIGIN
        detached = re.search(r"DROP TRIGGER IF EXISTS (\w+)", sql)
        if detached:
            self._triggers.pop(detached.group(1), None)

    async def fetchval(self, sql: str, *_args: object) -> bool:
        self.calls.append(sql)
        relation = re.search(r"to_regclass\('(\w+)'\) IS NOT NULL", sql)
        if relation is not None:
            return relation.group(1) in self._relations
        trigger = re.search(r"FROM pg_trigger\b.*?tgname = '(\w+)'", sql, re.DOTALL)
        if trigger is not None:
            name = trigger.group(1)
            # Answer the question the SQL actually asks, by running it. No row,
            # no match; otherwise the statement's own conditions on `tgenabled`
            # are evaluated against the character this row carries. A check
            # that merely spotted the column would accept a predicate that
            # discriminates nothing.
            tgenabled = self._triggers.get(name)
            if tgenabled is None:
                return False
            return _tgenabled_predicate_holds(sql, tgenabled)
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

    def drop_trigger(self, name: str) -> None:
        """Make the catalogue report a trigger as gone, as a DROP would."""
        self._triggers.pop(name, None)

    def disable_trigger(self, name: str) -> None:
        """Leave the trigger attached but stopped, as DISABLE TRIGGER would.

        Kept apart from `drop_trigger` because it is the case that slips
        through: the pg_trigger row is still there, so anything asking only
        whether a trigger EXISTS says the rollup is being maintained while
        nothing is maintaining it. It stays present here for exactly that
        reason, carrying the `tgenabled` PostgreSQL would leave on it.
        """
        self._triggers[name] = _TGENABLED_DISABLED


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
            "That is a full GROUP BY over agent_events under SHARE ROW EXCLUSIVE, "
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
