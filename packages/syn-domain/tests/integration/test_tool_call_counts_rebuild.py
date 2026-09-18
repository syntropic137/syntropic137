"""The tool-call tally can be reconstructed, against a real Postgres (#1322).

Everything else that covers ``tool_call_counts`` drives a double, which can
only ever say WHICH statements were issued. That was enough to miss the defect
this file exists for: startup decided whether to fill the tally by asking
``to_regclass`` - does the TABLE exist - and a table truncated by a projection
rebuild answers yes. The read model came back up with an empty tally and
reported zero tool calls for every session, indefinitely. A recording fake
cannot tell you that, because the statements were all perfectly good; it was
the rows that were gone.

So these tests run the module's own SQL, unmodified, against a real database:
seed ``agent_events``, build the tally through the real entry point, destroy
it the ways a real deployment destroys it, and check the rows that come back
against counts written out by hand - and against the ``GROUP BY`` the tally is
defined to equal.

``agent_events`` here is an ordinary table rather than a compressed
hypertable. Compression is why the old query was slow; it has no bearing on
which rows a ``GROUP BY`` returns, and a plain table lets this run anywhere
Postgres runs. Everything the tally itself touches is the real thing.

The last group goes further and drives the LIFECYCLES that have to reach the
recount - the coordinator's ``rebuild_projection`` and
``AgentEventStore.initialize`` with auto-creation off - because the recount
being correct was never the problem; being called was. Those run the real
migration file against a database prepared the way a deploy prepares one, and
cover the two states a double cannot construct honestly: a tally backfilled
while the previous version of the application was still appending events it
does not tally, and a startup as a role that holds no CREATE privilege.

Each test gets its own schema, so this never sees - or damages - the
``agent_events`` other integration tests share. The startup tests get their
own database instead, for a reason the fixture explains.

    uv run pytest -m integration \\
        packages/syn-domain/tests/integration/test_tool_call_counts_rebuild.py
"""

from __future__ import annotations

import asyncio
import pathlib
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any, cast
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import asyncpg
import pytest

from syn_domain import tool_call_counts
from syn_shared.events import TOKEN_USAGE, TOOL_EXECUTION_COMPLETED, TOOL_EXECUTION_STARTED

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, AsyncIterator

pytestmark = pytest.mark.integration

# Columns as 002_agent_events.sql declares them, minus the hypertable. The
# tally reads ``event_type``, ``session_id`` and ``execution_id``; the rest are
# here so a row the production writer would accept is a row this accepts.
_AGENT_EVENTS_DDL = """
CREATE TABLE agent_events (
    time TIMESTAMPTZ NOT NULL,
    event_type TEXT NOT NULL,
    session_id TEXT NOT NULL,
    execution_id TEXT,
    phase_id TEXT,
    data JSONB NOT NULL
)
"""

_INSERT_EVENT = """
INSERT INTO agent_events (time, event_type, session_id, execution_id, phase_id, data)
VALUES (now(), $1, $2, $3, 'implement', $4::jsonb)
"""

#: What the tally is defined to equal, spelled out here rather than imported,
#: so that changing ``BACKFILL_SQL`` cannot quietly change what it is checked
#: against.
_REFERENCE_SQL = """
SELECT session_id, COALESCE(execution_id, '') AS execution_id, COUNT(*)::bigint AS tool_calls
FROM agent_events
WHERE event_type = 'tool_execution_completed'
GROUP BY session_id, COALESCE(execution_id, '')
"""

_TALLY_SQL = f"SELECT session_id, execution_id, tool_calls FROM {tool_call_counts.TABLE}"


class _Event(tuple[str, str, str | None, str]):
    """``(event_type, session_id, execution_id, tool_name)``."""

    __slots__ = ()


def _tool(session_id: str, execution_id: str | None, tool_name: str = "Bash") -> _Event:
    return _Event((TOOL_EXECUTION_COMPLETED, session_id, execution_id, tool_name))


#: One page of plausible history. Two sessions under one execution, one session
#: under two executions, events with no execution at all, subagent delegations
#: (``Task``/``Agent``), and three kinds of event that are not tool calls - all
#: of which the count has to get right at once, because each is a way a
#: plausible wrong implementation stays green on the others.
_SEEDED_HISTORY: tuple[_Event, ...] = (
    _tool("sess-a", "exec-1"),
    _tool("sess-a", "exec-1", "Task"),
    _tool("sess-a", "exec-1", "Agent"),
    _tool("sess-a", "exec-2"),
    # Same execution, different session: an execution is not one session, which
    # is why the tally is keyed by the pair.
    _tool("sess-b", "exec-1"),
    _tool("sess-b", "exec-1", "Task"),
    # No execution. The count these replaced was a COUNT(*) with no join, so
    # dropping these would silently lower every ad-hoc session's total.
    _tool("sess-b", None),
    _tool("sess-b", None),
    _tool("sess-c", None),
    # Not tool calls. A tally that counted rows instead of tool calls, or that
    # counted starts as well as completions, would double sess-a's total.
    _Event((TOOL_EXECUTION_STARTED, "sess-a", "exec-1", "Bash")),
    _Event((TOKEN_USAGE, "sess-a", "exec-1", "")),
    _Event(("session_summary", "sess-c", None, "")),
)

#: Counted by hand from ``_SEEDED_HISTORY``, on purpose: a number this test
#: worked out for itself is the only kind that can disagree with the code.
_EXPECTED_TALLY: dict[tuple[str, str], int] = {
    ("sess-a", "exec-1"): 3,
    ("sess-a", "exec-2"): 1,
    ("sess-b", "exec-1"): 2,
    ("sess-b", ""): 2,
    ("sess-c", ""): 1,
}
_EXPECTED_BY_SESSION = {"sess-a": 4, "sess-b": 4, "sess-c": 1}
_EXPECTED_BY_EXECUTION = {"exec-1": 5, "exec-2": 1}


async def _seed(conn: asyncpg.Connection, events: tuple[_Event, ...]) -> None:
    for event_type, session_id, execution_id, tool_name in events:
        await conn.execute(
            _INSERT_EVENT,
            event_type,
            session_id,
            execution_id,
            f'{{"tool_name": "{tool_name}"}}',
        )


async def _stored_tally(conn: asyncpg.Connection) -> dict[tuple[str, str], int]:
    rows = await conn.fetch(_TALLY_SQL)
    return {(r["session_id"], r["execution_id"]): r["tool_calls"] for r in rows}


async def _reference_tally(conn: asyncpg.Connection) -> dict[tuple[str, str], int]:
    rows = await conn.fetch(_REFERENCE_SQL)
    return {(r["session_id"], r["execution_id"]): r["tool_calls"] for r in rows}


@pytest.fixture
async def pool(test_infrastructure) -> AsyncGenerator[asyncpg.Pool]:  # shared fixture
    """A pool whose every connection sees only this test's own schema."""
    schema = f"tally_rebuild_{uuid4().hex[:10]}"
    admin = await asyncpg.connect(test_infrastructure.timescaledb_url)
    await admin.execute(f"CREATE SCHEMA {schema}")

    # As a startup parameter, not a SET: the pool runs RESET ALL when a
    # connection goes back, which would undo anything set on the session.
    created = await asyncpg.create_pool(
        test_infrastructure.timescaledb_url,
        server_settings={"search_path": schema},
        min_size=2,
        max_size=4,
    )
    assert created is not None
    async with created as db:
        async with db.acquire() as conn:
            await conn.execute(_AGENT_EVENTS_DDL)
            await _seed(conn, _SEEDED_HISTORY)
        yield db

    await admin.execute(f"DROP SCHEMA {schema} CASCADE")
    await admin.close()


async def test_a_new_install_counts_the_history_it_already_has(pool: asyncpg.Pool) -> None:
    """The baseline the rest of this file corrupts and repairs."""
    async with pool.acquire() as conn:
        await tool_call_counts.ensure_ready(conn, skip_auto_create=False)

        assert await _stored_tally(conn) == _EXPECTED_TALLY
        assert await _stored_tally(conn) == await _reference_tally(conn)


async def test_the_counts_reach_the_readers_the_endpoints_call(pool: asyncpg.Pool) -> None:
    """Two questions, one set of rows - which is the reason for the pair key.

    ``by_execution`` must not report the rows that carried no execution: the
    query it replaced ended in ``WHERE execution_id IS NOT NULL``, and the
    sentinel that stands in for NULL here is not an execution anyone can open.
    """
    async with pool.acquire() as conn:
        await tool_call_counts.ensure_ready(conn, skip_auto_create=False)

        assert await tool_call_counts.by_session(conn) == _EXPECTED_BY_SESSION
        assert await tool_call_counts.by_execution(conn) == _EXPECTED_BY_EXECUTION
        assert await tool_call_counts.by_session(conn, ["sess-b"]) == {"sess-b": 4}
        assert await tool_call_counts.by_execution(conn, ["exec-1"]) == {"exec-1": 5}


async def test_a_truncated_tally_is_rebuilt_on_the_next_startup(pool: asyncpg.Pool) -> None:
    """The incident, reproduced: a rebuild emptied the table and startup shrugged.

    ``to_regclass`` said the table was there, so nothing refilled it and every
    session reported zero tool calls. What makes this the real test and not the
    unit one is the last line: the rows are back, and they are the right rows.
    """
    async with pool.acquire() as conn:
        await tool_call_counts.ensure_ready(conn, skip_auto_create=False)
        await conn.execute(f"TRUNCATE TABLE {tool_call_counts.TABLE}")
        assert await _stored_tally(conn) == {}

        await tool_call_counts.ensure_ready(conn, skip_auto_create=False)

        assert await _stored_tally(conn) == _EXPECTED_TALLY
        assert await tool_call_counts.by_session(conn) == _EXPECTED_BY_SESSION


async def test_rebuild_repairs_counts_that_are_present_and_wrong(pool: asyncpg.Pool) -> None:
    """Blank is the detectable corruption; wrong is the dangerous one.

    No probe can spot a populated tally holding bad numbers - a page showing
    them looks exactly like a page showing good ones. ``rebuild`` is the answer,
    and it has to fix all three shapes of wrong at once: a count that drifted,
    a row that vanished, and a row for something that never happened.
    """
    async with pool.acquire() as conn:
        await tool_call_counts.ensure_ready(conn, skip_auto_create=False)
        await conn.execute(f"UPDATE {tool_call_counts.TABLE} SET tool_calls = 9999")
        await conn.execute(
            f"DELETE FROM {tool_call_counts.TABLE} WHERE session_id = 'sess-c'",
        )
        await conn.execute(
            f"INSERT INTO {tool_call_counts.TABLE} VALUES ('sess-ghost', 'exec-ghost', 7)"
        )

        await tool_call_counts.rebuild(conn)

        assert await _stored_tally(conn) == _EXPECTED_TALLY
        assert await _stored_tally(conn) == await _reference_tally(conn)


async def test_rebuilding_twice_is_rebuilding_once(pool: asyncpg.Pool) -> None:
    """An operator who is not sure whether the first run worked will run it again.

    ``BACKFILL_SQL`` ends in ``ON CONFLICT DO UPDATE``, so a rebuild that
    forgot to empty the table first would still look right here - unless it
    left rows behind that the history no longer justifies, which is what the
    ghost row is for.
    """
    async with pool.acquire() as conn:
        await tool_call_counts.ensure_ready(conn, skip_auto_create=False)
        await conn.execute(
            f"INSERT INTO {tool_call_counts.TABLE} VALUES ('sess-ghost', 'exec-ghost', 7)"
        )

        await tool_call_counts.rebuild(conn)
        await tool_call_counts.rebuild(conn)

        assert await _stored_tally(conn) == _EXPECTED_TALLY


async def test_a_rebuild_cannot_run_past_an_uncommitted_increment(pool: asyncpg.Pool) -> None:
    """The coordination, observed rather than argued.

    A writer holds ``agent_events`` and the tally in ONE transaction. While it
    is open, ``rebuild`` must not get past emptying the table - if it did, it
    would recount from a snapshot that cannot see the writer's event and then
    overwrite the row the writer is about to increment, losing the tool call
    for good.

    TRUNCATE is what provides that: ACCESS EXCLUSIVE, so the writer's own
    insert into the tally is what blocks the rebuild. DELETE takes a lock too
    weak to stop a writer inserting a key the tally does not have yet, which is
    every session's first tool call.
    """
    async with pool.acquire() as writer, pool.acquire() as rebuilder:
        await tool_call_counts.ensure_ready(rebuilder, skip_auto_create=False)

        writer_txn = writer.transaction()
        await writer_txn.start()
        await _seed(writer, (_tool("sess-new", "exec-new"),))
        await tool_call_counts.record(
            writer,
            tool_call_counts.tally([(TOOL_EXECUTION_COMPLETED, "sess-new", "exec-new")]),
        )

        rebuilding = asyncio.create_task(tool_call_counts.rebuild(rebuilder))
        done, _pending = await asyncio.wait({rebuilding}, timeout=2.0)
        assert not done, "the rebuild emptied the tally while a writer was mid-transaction"

        await writer_txn.commit()
        await asyncio.wait_for(rebuilding, timeout=10.0)

    async with pool.acquire() as conn:
        assert await _stored_tally(conn) == await _reference_tally(conn)
        assert await _stored_tally(conn) == _EXPECTED_TALLY | {("sess-new", "exec-new"): 1}


# ---------------------------------------------------------------------------
# The two lifecycles that have to reach the recount
#
# Everything above calls ``ensure_ready`` and ``rebuild`` directly, and those
# functions were never the defect. The defect was that in the configuration we
# deploy, nothing called them: the tally was not in the projection registry, and
# startup repaired it only from the branch ``SYN_SKIP_AUTO_CREATE_TABLES=true``
# skips. So these two drive the entry points production drives, and check the
# rows that come out against the same ``GROUP BY``.
#
# They reach into ``syn_adapters`` from a ``syn-domain`` test, which the
# layering rule permits for tests and not for ``src``, and which is the point:
# the expectations these check against are the ones above, and a copy of
# ``_EXPECTED_TALLY`` in another package is a copy that drifts.
# ---------------------------------------------------------------------------


def _registered_projections(pool: asyncpg.Pool) -> list[object]:
    """The projection registry production builds, built the way production builds it.

    ``event_store`` and ``projection_store`` are placeholders because
    ``rebuild_projection`` uses neither - it deletes a checkpoint and calls the
    projection's own ``clear_all_data``. The pool is the argument that matters
    and it is the real one.
    """
    from syn_adapters.subscriptions import create_coordinator_service

    service = create_coordinator_service(
        event_store=cast("Any", object()),
        projection_store=cast("Any", object()),
        pool=pool,
    )
    return service._projections


async def test_the_application_projection_rebuild_recounts_the_tally(pool: asyncpg.Pool) -> None:
    """``rebuild_projection tool_call_counts``, end to end, against real rows.

    This is the operator action the read model was invisible to. An unregistered
    projection raises ``KeyError`` here, so reaching the rows at all is half the
    assertion; the other half is that they are the rows the history justifies
    rather than the wrong ones this test put there.
    """
    from event_sourcing import MemoryCheckpointStore, SubscriptionCoordinator

    async with pool.acquire() as conn:
        await tool_call_counts.ensure_ready(conn, skip_auto_create=False)
        await conn.execute(f"UPDATE {tool_call_counts.TABLE} SET tool_calls = 9999")
        await conn.execute(f"DELETE FROM {tool_call_counts.TABLE} WHERE session_id = 'sess-c'")

    coordinator = SubscriptionCoordinator(
        event_store=cast("Any", object()),
        checkpoint_store=MemoryCheckpointStore(),
        projections=cast("Any", _registered_projections(pool)),
    )
    await coordinator.rebuild_projection(tool_call_counts.PROJECTION_NAME)

    async with pool.acquire() as conn:
        assert await _stored_tally(conn) == _EXPECTED_TALLY
        assert await _stored_tally(conn) == await _reference_tally(conn)


def _migration_sql() -> str:
    """The migration an operator applies by hand, read from the file that ships.

    Located through the installed package rather than by counting ``..`` up
    from this file, so moving either directory is a failure to import and not
    a test that quietly stops reading the real SQL. Running it verbatim is what
    makes these fail if the shipped migration and the module's own ``CREATE``
    statements ever drift apart.
    """
    import syn_adapters

    path = (
        pathlib.Path(syn_adapters.__file__).parent
        / "projection_stores/migrations"
        / tool_call_counts.MIGRATION
    )
    return path.read_text()


#: What migration 004 USED to end with, and the reason it no longer does. Kept
#: here, in the test that needs the hazard, so the state can still be
#: constructed after the migration stopped producing it - a fix that only works
#: because nothing creates the bad state any more is a fix that unravels the
#: first time someone adds a backfill back.
_LEGACY_MIGRATION_BACKFILL = f"""
INSERT INTO {tool_call_counts.TABLE} (session_id, execution_id, tool_calls)
SELECT session_id, COALESCE(execution_id, ''), COUNT(*)
FROM agent_events
WHERE event_type = 'tool_execution_completed'
GROUP BY session_id, COALESCE(execution_id, '')
ON CONFLICT (session_id, execution_id) DO UPDATE
SET tool_calls = EXCLUDED.tool_calls
"""


@asynccontextmanager
async def _hand_migrated_database(admin_url: str) -> AsyncIterator[tuple[str, asyncpg.Connection]]:
    """A database prepared the way a production deploy prepares one.

    Its own DATABASE, not its own schema, because ``EventStoreSchema.validate``
    looks ``agent_events`` up in ``public`` specifically - so a startup test
    that hid in a private schema would fail before it reached the tally.

    ``agent_events`` is created and seeded here; the tally's tables come from
    running the real migration file. Nothing else is prepared: what happens
    next is whatever the test does, and then entirely
    ``AgentEventStore.initialize``.

    Yields the DSN and an open connection to it, the second because every
    caller wants one and closing it in the wrong order leaves ``DROP DATABASE``
    blocked on its own fixture.
    """
    name = f"tally_startup_{uuid4().hex[:10]}"
    admin = await asyncpg.connect(admin_url)
    await admin.execute(f"CREATE DATABASE {name}")

    parts = urlsplit(admin_url)
    dsn = urlunsplit(parts._replace(path=f"/{name}"))

    conn = await asyncpg.connect(dsn)
    try:
        await conn.execute(_AGENT_EVENTS_DDL)
        await _seed(conn, _SEEDED_HISTORY)
        await conn.execute(_migration_sql())
        yield dsn, conn
    finally:
        await conn.close()
        await admin.execute(f"DROP DATABASE {name} WITH (FORCE)")
        await admin.close()


@pytest.fixture
async def hand_migrated(
    test_infrastructure,
) -> AsyncGenerator[tuple[str, asyncpg.Connection]]:  # shared fixture
    async with _hand_migrated_database(test_infrastructure.timescaledb_url) as prepared:
        yield prepared


async def _start_the_application(dsn: str) -> None:
    """``AgentEventStore.initialize`` in the deployed configuration, and nothing else.

    ``skip_auto_create=True`` is what ``SYN_SKIP_AUTO_CREATE_TABLES=true``
    produces and is what we ship.
    """
    from syn_adapters.events.schema import EventStoreSchema
    from syn_adapters.events.store import AgentEventStore

    store = AgentEventStore(dsn, schema=EventStoreSchema(skip_auto_create=True))
    try:
        await store.initialize()
    finally:
        await store.close()


async def test_the_migration_creates_the_tally_empty_and_unstamped(
    hand_migrated: tuple[str, asyncpg.Connection],
) -> None:
    """The precondition the next two rest on, asserted rather than assumed.

    If migration 004 ever backfills again, the startup tests below would be
    starting from a state they did not intend and could pass while the hazard
    they exist for went unmeasured.
    """
    _dsn, conn = hand_migrated

    assert await _stored_tally(conn) == {}
    assert await conn.fetchval(f"SELECT count(*) FROM {tool_call_counts.VERSION_TABLE}") == 0


async def test_the_deployed_startup_path_repairs_a_blank_tally(
    hand_migrated: tuple[str, asyncpg.Connection],
) -> None:
    """Auto-creation off - the one configuration that used to skip the repair.

    Before this fix, coming up against exactly this database left the tally as
    it found it and every session on the dashboard reported zero tool calls,
    indefinitely, with nothing in the logs.
    """
    dsn, conn = hand_migrated

    await _start_the_application(dsn)

    assert await _stored_tally(conn) == _EXPECTED_TALLY
    assert await _stored_tally(conn) == await _reference_tally(conn)


async def test_a_tally_backfilled_before_the_old_writer_stopped_is_recounted(
    hand_migrated: tuple[str, asyncpg.Connection],
) -> None:
    """The upgrade window, walked through in order (#1322).

    A migration runs against a live database. The application still serving
    while it runs is the previous version - the one being replaced precisely
    because it does not maintain this tally - so the sequence is:

    1. the migration backfills, and the tally is momentarily correct;
    2. the old writer appends a tool call to ``agent_events`` and does not
       tally it, because it has never heard of the table;
    3. the new application starts.

    After step 2 the table is NON-BLANK and SHORT, and nothing about the rows
    says so. "Does it have rows" - the only question startup used to ask -
    cannot tell this from a correct tally, and the coordinator's other net
    misses too: a first registration has no checkpoint to mismatch, so
    ``clear_all_data`` is never called. The undercount was permanent.

    The assertion is the task's: after step 3 the stored tally equals a fresh
    ``GROUP BY`` over ``agent_events``, with nothing run by hand.
    """
    dsn, conn = hand_migrated

    await conn.execute(_LEGACY_MIGRATION_BACKFILL)
    assert await _stored_tally(conn) == _EXPECTED_TALLY, "the backfill is the starting point"

    await _seed(conn, (_tool("sess-a", "exec-1"),))
    short = await _stored_tally(conn)
    assert short != await _reference_tally(conn), (
        "the legacy append did not open a gap, so this test is not measuring one"
    )

    await _start_the_application(dsn)

    assert await _stored_tally(conn) == await _reference_tally(conn)
    assert await _stored_tally(conn) == _EXPECTED_TALLY | {("sess-a", "exec-1"): 3}


async def test_a_second_startup_does_not_pay_for_the_recount_again(
    hand_migrated: tuple[str, asyncpg.Connection],
) -> None:
    """Once per definition, not once per restart.

    The recount is the full ``GROUP BY`` over ``agent_events`` this whole
    change exists to stop running, and at startup it blocks the application
    coming up. The stamp is what bounds it - so a test that only proved
    recounting happens would be describing a worse system than the one before.
    """
    dsn, conn = hand_migrated
    await _start_the_application(dsn)
    await conn.execute(f"UPDATE {tool_call_counts.TABLE} SET tool_calls = 9999")

    await _start_the_application(dsn)

    assert all(count == 9999 for count in (await _stored_tally(conn)).values()), (
        "a stamped tally was recounted on a restart"
    )


async def test_the_application_starts_as_a_role_that_cannot_create_tables(
    hand_migrated: tuple[str, asyncpg.Connection],
) -> None:
    """The other blocker, against the privileges a hand-migrated deploy is entitled to.

    ``CREATE TABLE IF NOT EXISTS`` reads as harmless and is not: PostgreSQL
    checks CREATE on the schema before it checks whether the table is already
    there, so issuing it as a role that owns no schema raises
    ``InsufficientPrivilegeError`` and the application never comes up - over a
    table that exists and is perfectly fine.

    The role below is the posture the "migrations own DDL" contract describes:
    full DML on the tables it maintains, including the TRUNCATE a recount
    needs, and no CREATE anywhere. Startup must complete, and must arrive at
    the same rows.
    """
    dsn, conn = hand_migrated
    role = f"tally_app_{uuid4().hex[:8]}"
    await conn.execute(f"CREATE ROLE {role} LOGIN PASSWORD 'tally'")
    await conn.execute(f"REVOKE ALL ON SCHEMA public FROM {role}")
    await conn.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
    await conn.execute(f"GRANT USAGE ON SCHEMA public TO {role}")
    await conn.execute(f"GRANT SELECT ON agent_events TO {role}")
    for table in (tool_call_counts.TABLE, tool_call_counts.VERSION_TABLE):
        await conn.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE, TRUNCATE ON {table} TO {role}")

    parts = urlsplit(dsn)
    unprivileged = urlunsplit(parts._replace(netloc=f"{role}:tally@{parts.hostname}:{parts.port}"))

    probe = await asyncpg.connect(unprivileged)
    try:
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await probe.execute("CREATE TABLE cannot_create_this (x INT)")
    finally:
        await probe.close()

    await _start_the_application(unprivileged)

    assert await _stored_tally(conn) == _EXPECTED_TALLY
    assert await _stored_tally(conn) == await _reference_tally(conn)

    await conn.execute(f"REASSIGN OWNED BY {role} TO CURRENT_USER")
    await conn.execute(f"DROP OWNED BY {role}")
    await conn.execute(f"DROP ROLE {role}")
