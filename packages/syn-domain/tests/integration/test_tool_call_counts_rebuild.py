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

Each test gets its own schema, so this never sees - or damages - the
``agent_events`` other integration tests share.

    uv run pytest -m integration \\
        packages/syn-domain/tests/integration/test_tool_call_counts_rebuild.py
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING
from uuid import uuid4

import asyncpg
import pytest

from syn_domain import tool_call_counts
from syn_shared.events import TOKEN_USAGE, TOOL_EXECUTION_COMPLETED, TOOL_EXECUTION_STARTED

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

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
        await tool_call_counts.ensure_ready(conn)

        assert await _stored_tally(conn) == _EXPECTED_TALLY
        assert await _stored_tally(conn) == await _reference_tally(conn)


async def test_the_counts_reach_the_readers_the_endpoints_call(pool: asyncpg.Pool) -> None:
    """Two questions, one set of rows - which is the reason for the pair key.

    ``by_execution`` must not report the rows that carried no execution: the
    query it replaced ended in ``WHERE execution_id IS NOT NULL``, and the
    sentinel that stands in for NULL here is not an execution anyone can open.
    """
    async with pool.acquire() as conn:
        await tool_call_counts.ensure_ready(conn)

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
        await tool_call_counts.ensure_ready(conn)
        await conn.execute(f"TRUNCATE TABLE {tool_call_counts.TABLE}")
        assert await _stored_tally(conn) == {}

        await tool_call_counts.ensure_ready(conn)

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
        await tool_call_counts.ensure_ready(conn)
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
        await tool_call_counts.ensure_ready(conn)
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
        await tool_call_counts.ensure_ready(rebuilder)

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
