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
   it. Migration 004 creates the table EMPTY, so the deployment came up
   reporting zero tool calls for every session that had ever run.

Both failures are silent, and both are invisible to a test that calls
``ensure_ready`` or ``rebuild`` directly: those functions were always correct.
What was wrong was who called them. So nothing here calls either one. These
drive ``create_coordinator_service`` and ``AgentEventStore.initialize``, the
two entry points production actually uses, and assert the recount came out the
other end.

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
from syn_domain.tool_call_counts import ToolCallCountsNotWiredError, ToolCallCountsProjection

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

    def __init__(self) -> None:
        self.statements: list[str] = []
        self.transactional: list[str] = []
        self.open_transactions = 0

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
        # "has agent_events anything to count?" -> yes.
        # "is the tally blank?" -> yes.
        return True

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

    ``True`` is the case that was broken and is the reason for the parameter:
    it is what ``SYN_SKIP_AUTO_CREATE_TABLES=true`` produces, it is what we
    deploy, and it is the value under which startup used to do nothing at all.
    ``False`` is here so a fix that merely moved the bug to the other branch
    fails too.
    """
    conn = _Conn()

    await _start_the_store(skip_auto_create=skip_auto_create, conn=conn)

    assert conn.issued(tool_call_counts.CREATE_TABLE_SQL)
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
