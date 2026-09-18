"""The two wirings the tool-call tally's correctness rests on (#1322).

The tally is a read model that no replay refills. Every tool call is counted
in the transaction that stores the event, which is what makes the number
incapable of drifting from ``agent_events`` - and also what makes the ordinary
projection machinery walk straight past it. So two things have to be wired by
hand, and each was wrong in exactly one configuration:

1. **The rebuild.** ``SubscriptionCoordinator`` discards and rebuilds read
   models on a version bump or an operator's ``rebuild_projection``. The tally
   was not in the registry, so that rebuild emptied the table (it is in the
   same database) and nothing refilled it.

2. **Startup.** The repair ran inside ``if not self._skip_auto_create``, so
   ``SYN_SKIP_AUTO_CREATE_TABLES=true`` - the configuration we deploy - skipped
   it. The deployment came up reporting zero tool calls for every session that
   had ever run. Moving the repair out of that branch then took the DDL with
   it, and ``CREATE TABLE IF NOT EXISTS`` against a role holding no CREATE
   privilege does not start at all. Sections 3 and 4 are the two halves that
   had to be separated: the flag governs DDL and nothing else, and the rows
   are decided by a version stamp rather than by whether the table has
   anything in it - because a migration-backfilled tally has rows and is
   short, and "has rows" accepted it forever.

Both failures are silent, and both are invisible to a test that calls
``ensure_ready`` or ``rebuild`` directly: those functions were always correct.
What was wrong was who called them, and with what. So nothing here calls
either one. These drive ``create_coordinator_service`` and
``AgentEventStore.initialize``, the two entry points production actually uses,
and assert the recount came out the other end.

The database is a double, deliberately: what is under test is which call
reaches which SQL, not what Postgres does with it. The rows themselves are
checked against a live server in
``packages/syn-domain/tests/integration/test_tool_call_counts_rebuild.py``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

import pytest
from event_sourcing import MemoryCheckpointStore, ProjectionResult, SubscriptionCoordinator

from syn_adapters.events.schema import EventStoreSchema
from syn_adapters.events.store import AgentEventStore
from syn_adapters.subscriptions import create_coordinator_service
from syn_domain import tool_call_counts
from syn_domain.tool_call_counts import (
    ToolCallCountsNotMigratedError,
    ToolCallCountsNotWiredError,
    ToolCallCountsProjection,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

pytestmark = pytest.mark.unit

#: What ``EventStoreSchema.validate`` must find, or startup fails before it
#: ever reaches the tally. Mirrors ``EXPECTED_COLUMNS``; a schema mismatch is
#: a different test's subject (``events/test_schema_validation.py``).
_AGENT_EVENTS_COLUMNS = (
    ("time", "timestamp with time zone"),
    ("event_type", "text"),
    ("session_id", "text"),
    ("execution_id", "text"),
    ("phase_id", "text"),
    ("data", "jsonb"),
)

#: The DDL ``ensure_schema`` runs only when auto-creation is ON. Asserting its
#: ABSENCE is what stops the startup test passing for the wrong reason: if the
#: flag were not really in effect, the repair would be running from the branch
#: that always worked.
_AGENT_EVENTS_DDL_MARKER = "CREATE TABLE IF NOT EXISTS agent_events"


class _Transaction:
    def __init__(self, conn: _Conn) -> None:
        self._conn = conn

    async def __aenter__(self) -> _Conn:
        self._conn.open_transactions += 1
        return self._conn

    async def __aexit__(self, *_exc: object) -> bool:
        self._conn.open_transactions -= 1
        return False


class _Conn:
    """A database holding history, and a tally that is blank.

    The state a hand-migrated deployment is in on its first start after this
    feature shipped, and the state a projection rebuild leaves behind. Both are
    the case the repair exists for, so both answers are fixed here rather than
    defaulted: a double that reported the tally as already full would let a
    startup that skips the repair pass.
    """

    def __init__(
        self,
        *,
        tables_exist: bool = True,
        tally_is_blank: bool = True,
        stamped_version: int | None = None,
    ) -> None:
        self.statements: list[str] = []
        self.transactional: list[str] = []
        self.open_transactions = 0
        self.tables_exist = tables_exist
        self.tally_is_blank = tally_is_blank
        self.stamped_version = stamped_version

    def _record(self, query: str) -> None:
        self.statements.append(query)
        if self.open_transactions:
            self.transactional.append(query)

    async def execute(self, query: str, *_args: object) -> str:
        self._record(query)
        return "OK"

    async def fetch(self, query: str, *_args: object) -> Sequence[Any]:
        self._record(query)
        if "information_schema" in query:
            return [
                {"column_name": name, "data_type": data_type}
                for name, data_type in _AGENT_EVENTS_COLUMNS
            ]
        return []

    async def fetchval(self, query: str, *_args: object) -> object:
        self._record(query)
        # "do the tally's tables exist?" -> as configured.
        if "to_regclass" in query:
            return self.tables_exist
        # "what definition version were these rows recounted to?" -> none, the
        # state migration 004 leaves and the one a startup must not accept.
        # Asked before the tally's own name, which this table's contains.
        if tool_call_counts.VERSION_TABLE in query:
            return self.stamped_version
        # "has agent_events anything to count?" -> yes.
        if "agent_events" in query:
            return True
        # "is the tally blank?" -> as configured.
        return self.tally_is_blank

    def transaction(self) -> _Transaction:
        return _Transaction(self)

    def issued(self, sql: str) -> bool:
        return any(sql.strip() in statement for statement in self.statements)


class _Acquire:
    def __init__(self, conn: _Conn) -> None:
        self._conn = conn

    async def __aenter__(self) -> _Conn:
        return self._conn

    async def __aexit__(self, *_exc: object) -> bool:
        return False


class _Pool:
    def __init__(self, conn: _Conn) -> None:
        self.conn = conn

    def acquire(self) -> _Acquire:
        return _Acquire(self.conn)


def _recount_ran(conn: _Conn) -> bool:
    """Did a full recount from ``agent_events`` reach the database?

    Both halves, because either alone is a different and worse outcome than
    doing nothing: a TRUNCATE with no backfill empties the tally, and a
    backfill with no TRUNCATE leaves rows the history no longer justifies.
    """
    return conn.issued("TRUNCATE TABLE") and conn.issued(tool_call_counts.BACKFILL_SQL)


# ---------------------------------------------------------------------------
# 1. The rebuild lifecycle
# ---------------------------------------------------------------------------


def _registry(pool: _Pool | None) -> list[Any]:
    """The projections production registers, built exactly as production builds them."""
    dummy = cast("Any", object())
    service = create_coordinator_service(
        event_store=dummy,
        projection_store=dummy,
        pool=cast("Any", pool),
    )
    return service._projections  # the registry, read as coordinator_helpers reads it


async def test_an_operator_rebuilding_the_read_models_recounts_the_tally() -> None:
    """The whole finding, in one call.

    ``rebuild_projection`` raises ``KeyError`` for a name it does not know, so
    reaching the recount at all is the proof of registration, and the recount
    arriving at the pool is the proof that the registration does something. An
    entry that was merely present, or present with the hook left as the
    inherited no-op, fails here.
    """
    conn = _Conn()
    coordinator = SubscriptionCoordinator(
        event_store=cast("Any", object()),
        checkpoint_store=MemoryCheckpointStore(),
        projections=_registry(_Pool(conn)),
    )

    await coordinator.rebuild_projection(tool_call_counts.PROJECTION_NAME)

    assert _recount_ran(conn), (
        f"the rebuild issued {conn.statements}, which does not recount the tally"
    )


async def test_the_recount_a_rebuild_triggers_is_one_transaction() -> None:
    """Emptying and refilling must not be separately visible to a reader.

    The lifecycle hook is the one caller that runs against a live deployment
    with pages being served, so this is where a non-atomic recount would show
    every session as having made zero tool calls for the width of the gap.
    """
    conn = _Conn()
    coordinator = SubscriptionCoordinator(
        event_store=cast("Any", object()),
        checkpoint_store=MemoryCheckpointStore(),
        projections=_registry(_Pool(conn)),
    )

    await coordinator.rebuild_projection(tool_call_counts.PROJECTION_NAME)

    assert conn.issued("TRUNCATE TABLE")
    assert all(
        statement in conn.transactional
        for statement in conn.statements
        if "TRUNCATE TABLE" in statement or tool_call_counts.BACKFILL_SQL.strip() in statement
    )
    assert conn.open_transactions == 0


async def test_replaying_the_events_does_not_count_them_a_second_time() -> None:
    """The reason this projection handles no events, asserted rather than assumed.

    The tally is incremented by the write that stores the event. A handler that
    also incremented on replay would double every number in the system, and
    would do it only on the next restart - long after the change that caused
    it. SKIP, and not one statement.
    """
    conn = _Conn()
    projection = ToolCallCountsProjection(pool=_Pool(conn))

    result = await projection.handle_event(cast("Any", object()), cast("Any", object()))

    assert result is ProjectionResult.SKIP
    assert conn.statements == []


async def test_a_tally_projection_with_no_database_refuses_instead_of_pretending() -> None:
    """Silence here is the failure being fixed, so it is not available.

    A rebuild that logged a warning and returned would report success while
    leaving the read model wrong - which is indistinguishable, from the
    outside, from not being registered at all.
    """
    with pytest.raises(ToolCallCountsNotWiredError):
        await ToolCallCountsProjection().clear_all_data()


# ---------------------------------------------------------------------------
# 2. Startup, in the configuration we deploy
# ---------------------------------------------------------------------------


async def _start_the_store(*, skip_auto_create: bool, conn: _Conn) -> None:
    """Run ``AgentEventStore.initialize`` against the double, nothing stubbed but the pool."""
    import asyncpg

    store = AgentEventStore(
        "postgresql://double/observability",
        schema=EventStoreSchema(skip_auto_create=skip_auto_create),
    )

    async def _create_pool(*_args: object, **_kwargs: object) -> _Pool:
        return _Pool(conn)

    original = asyncpg.create_pool
    asyncpg.create_pool = cast("Any", _create_pool)
    try:
        await store.initialize()
    finally:
        asyncpg.create_pool = cast("Any", original)


@pytest.mark.parametrize("skip_auto_create", [True, False])
async def test_startup_repairs_the_tally_whatever_the_auto_create_flag_says(
    skip_auto_create: bool,
) -> None:
    """Readiness and DDL are different jobs and no longer share a switch.

    ``True`` is the case that was broken first and is the reason for the
    parameter: it is what ``SYN_SKIP_AUTO_CREATE_TABLES=true`` produces, it is
    what we deploy, and it is the value under which startup used to do nothing
    at all. ``False`` is here so a fix that merely moved the bug to the other
    branch fails too.

    What the flag governs is the subject of the two tests below. It is not
    this one: the recount runs either way.
    """
    conn = _Conn()

    await _start_the_store(skip_auto_create=skip_auto_create, conn=conn)

    assert _recount_ran(conn), (
        f"startup with skip_auto_create={skip_auto_create} issued {conn.statements}, "
        "which leaves the tally blank"
    )


async def test_the_deployed_configuration_really_is_the_one_being_measured() -> None:
    """The guard on the test above: with the flag set, no table is auto-created.

    Without this, a regression that quietly stopped honouring
    ``skip_auto_create`` would make the interesting half of the parametrisation
    identical to the half that always passed, and the test would go on being
    green while measuring nothing.
    """
    conn = _Conn()

    await _start_the_store(skip_auto_create=True, conn=conn)

    assert not conn.issued(_AGENT_EVENTS_DDL_MARKER), (
        "agent_events was auto-created despite skip_auto_create=True"
    )


# ---------------------------------------------------------------------------
# 3. The flag governs DDL, and only DDL
# ---------------------------------------------------------------------------

#: Every statement this system may issue that requires CREATE privilege on the
#: tally's behalf. A deployment that applies its own migrations may be
#: connecting as a role that holds none, in which case each of these is not a
#: harmless no-op but a failed startup.
_TALLY_DDL = (
    tool_call_counts.CREATE_TABLE_SQL,
    tool_call_counts.CREATE_INDEX_SQL,
    tool_call_counts.CREATE_VERSION_TABLE_SQL,
)


async def test_the_deployment_that_owns_its_ddl_is_issued_none_of_it() -> None:
    """The blocker: the repair escaped the auto-create branch and took the DDL with it.

    ``CREATE TABLE IF NOT EXISTS`` reads as harmless and is not. It needs
    CREATE on the schema before it can decide the table is already there, so
    against the least-privileged role a hand-migrated deployment is entitled to
    use, this is the statement that refuses to start the application - for a
    table that exists.

    Asserted over every DDL statement the module owns rather than the one that
    happened to regress, because the next one added is the next one to leak.
    """
    conn = _Conn()

    await _start_the_store(skip_auto_create=True, conn=conn)

    leaked = [sql for sql in _TALLY_DDL if conn.issued(sql)]
    assert leaked == [], f"startup issued DDL a role without CREATE cannot run: {leaked}"


async def test_the_deployment_that_asked_for_auto_creation_still_gets_it() -> None:
    """The other direction, so "issue no DDL" cannot be satisfied by issuing none ever.

    Development and the test stack come up against an empty database with no
    migrations applied. If the flag is unset, the tables are this module's to
    create - all three of them, including the version table, without which
    nothing can record that a recount happened.
    """
    conn = _Conn()

    await _start_the_store(skip_auto_create=False, conn=conn)

    missing = [sql for sql in _TALLY_DDL if not conn.issued(sql)]
    assert missing == [], f"auto-creation was asked for and these were not created: {missing}"


async def test_a_deployment_missing_the_migration_is_told_so_at_startup() -> None:
    """Auto-creation off and the tables absent is an operator error, not a state to survive.

    The two alternatives are both worse. Creating them anyway is the bug
    above. Carrying on leaves an application whose every read of the tally
    fails on a missing relation, at request time, on the dashboard - so the
    first thing anyone sees is a page of errors rather than a startup log line
    naming the migration to run.
    """
    conn = _Conn(tables_exist=False)

    with pytest.raises(ToolCallCountsNotMigratedError) as raised:
        await _start_the_store(skip_auto_create=True, conn=conn)

    assert tool_call_counts.MIGRATION in str(raised.value)
    assert not any(conn.issued(sql) for sql in _TALLY_DDL), "created the tables it just refused to"


# ---------------------------------------------------------------------------
# 4. A tally that is populated and short
# ---------------------------------------------------------------------------


async def test_a_populated_tally_no_writer_of_it_produced_is_recounted() -> None:
    """The blocker, in the state the upgrade actually passes through (#1322).

    Migration 004 used to backfill. It runs against a live database, so the
    application still serving while it runs is the one that does not maintain
    this tally, and everything that version appends to ``agent_events`` before
    the new binary starts is counted in the history and missing from the
    backfilled rows.

    The table is then NON-BLANK, which was the only question startup asked, so
    the gap was accepted - and the coordinator does not cover it either, since
    a first registration has no checkpoint to mismatch and nothing calls
    ``clear_all_data``. Both nets missed and the undercount was permanent.

    ``stamped_version=None`` is that state and could not arise any other way:
    only ``rebuild`` writes the stamp, so its absence means no writer of this
    tally has ever produced these rows, whatever the rows look like.
    """
    conn = _Conn(tally_is_blank=False, stamped_version=None)

    await _start_the_store(skip_auto_create=True, conn=conn)

    assert _recount_ran(conn), (
        f"a populated but unstamped tally was accepted; startup issued {conn.statements}"
    )


async def test_a_tally_built_to_an_older_definition_is_recounted() -> None:
    """What the stamp buys beyond the one upgrade: a version, that can be bumped.

    Every other read model here recounts on a version bump because the
    coordinator compares its checkpoint's version. This one cannot - its
    ``handle_event`` is a no-op and a first registration has no checkpoint -
    so the stamp is where that guarantee lives instead. Change what a row
    means, bump ``TALLY_VERSION``, and every deployment recounts once.
    """
    conn = _Conn(tally_is_blank=False, stamped_version=tool_call_counts.TALLY_VERSION - 1)

    await _start_the_store(skip_auto_create=True, conn=conn)

    assert _recount_ran(conn), "rows built to a superseded definition were served as current"


async def test_a_stamped_tally_is_not_recounted_on_every_startup() -> None:
    """The cost ceiling, without which the fix above is the bug it is fixing.

    A recount is the full ``GROUP BY`` over ``agent_events`` that #1322 exists
    to stop running - unbounded by anything except how much the agents have
    done. Once per definition is the whole budget; once per restart would be
    worse than what was there before, because now it blocks startup.
    """
    conn = _Conn(tally_is_blank=False, stamped_version=tool_call_counts.TALLY_VERSION)

    await _start_the_store(skip_auto_create=True, conn=conn)

    assert not conn.issued(tool_call_counts.BACKFILL_SQL), "recounted a tally already at version"
    assert not conn.issued("TRUNCATE TABLE")


async def test_the_stamp_is_committed_with_the_rows_it_describes() -> None:
    """Separately committed, a crash between them can strand a lie.

    Rows-then-stamp leaves "stamped but never recounted" recoverable by
    nothing: every later startup reads a current version and walks past. In one
    transaction the only state a crash can leave is "recounted, unstamped",
    which the next startup fixes by recounting again - and recounting twice is
    recounting once.
    """
    conn = _Conn()

    await _start_the_store(skip_auto_create=True, conn=conn)

    assert conn.issued(tool_call_counts._STAMP_SQL)
    assert any(tool_call_counts._STAMP_SQL.strip() in sql for sql in conn.transactional), (
        "the version stamp was committed outside the recount's transaction"
    )
    assert conn.open_transactions == 0
