"""The usage rollup's backfill neither pauses ingest nor miscounts it (#1558 r2).

The first version created the trigger and ran the whole backfill in ONE
transaction. CREATE TRIGGER takes SHARE ROW EXCLUSIVE on agent_events, which
conflicts with every INSERT, so ingest stopped for the length of a full scan
of the usage events, at every first deploy and every reconcile.

Now the trigger commits first and the backfill runs afterwards in batches,
under no lock an insert waits on. Two claims, both tested here against a
real database with a writer inserting the whole time:

  1. INGEST CARRIES ON. The backfill is parked on a gate the test holds,
     inside a batch's open transaction and after that batch's real work.
     While it is parked, inserts commit and are visible to another session,
     the backfill holds no relation lock that conflicts with an INSERT's,
     and the writer's backend is never queued behind the backfill's. This
     is decided by the database's lock table, not by a clock: the measured
     version (#1860) failed on shared runners (#1952). A wait on someone
     else is not the backfill's doing and is not counted: the first
     lock-table version counted every wait, and failed on a runner whose
     TimescaleDB compression job reached the writer's chunk first (#1952).
  2. EVERY EVENT IS COUNTED EXACTLY ONCE. After the dust settles, the rollup
     equals a fresh aggregation of agent_events: per turn key (every token
     column and the observation count) and per summary row (as a multiset).
     The concurrent writer hits sessions the backfill has already passed,
     sessions it has not reached yet, the batch it is parked in, and
     brand-new ones, on the same model keys the backfill writes, so a missed
     or doubled event shows up.

MARKED ``integration``: CI runs it on push to main, PRs into release and the
weekly cron, not on PRs into main.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from syn_shared.events import SESSION_STARTED, SESSION_SUMMARY, TOKEN_USAGE

from .usage_rollup_seed import Row, copy_rows, prepare_pre_e1_schema, throwaway_database

if TYPE_CHECKING:
    import asyncpg

pytestmark = pytest.mark.integration

HISTORY_SESSIONS = 300
TURNS_PER_SESSION = 50
BATCH_SESSIONS = 5  # many short transactions, so the writer interleaves with them
LIVE_INSERTS = 20  # the writer is up and committing before the rollup exists
PARKED_INSERTS = 10  # commits required while the backfill is parked mid-batch
AFTER_INSERTS = 5  # and after it finishes, before the counts are compared
POLL_S = 0.01  # how often a wait re-reads its condition; never a bound
HANG_GUARD_S = 60.0  # a wait that has not ended by now never will: fail, not hang
_MODELS = ("claude-sonnet-5", "claude-haiku-4-5-20251001")
_T0 = datetime(2026, 9, 1, tzinfo=UTC)
# The writer's rows start here, clear of the history's (at most _T0 + 1h + 300 s).
_WRITER_T0 = _T0 + timedelta(seconds=10_000)

# The gate: appended to every backfill batch, so the batch blocks on it inside
# its open transaction, after its real statements, while the test holds it.
# The two-key form shows as objsubid 2 in pg_locks and cannot collide with the
# bigint keys in syn_adapters.advisory_locks.
_GATE = (1952, 1860)
_GATE_SQL = "SELECT pg_advisory_xact_lock(1952, 1860) WHERE $1::text[] IS NOT NULL"
_PARKED_AT_GATE = """
SELECT EXISTS (
    SELECT 1 FROM pg_locks
    WHERE pid = $1 AND NOT granted AND locktype = 'advisory'
      AND classid = 1952 AND objid = 1860 AND objsubid = 2
)
"""
# Every lock the writer ($1) is queued on while the backfill ($2) is one of
# the backends it waits for. pg_blocking_pids counts holders and the waiters
# queued ahead, so a lock the backfill holds, or one a third party wants and
# cannot get past the backfill, both show here.
_WAITING_ON_BACKFILL = """
SELECT locktype, mode, relation::regclass::text AS relation
FROM pg_locks WHERE pid = $1 AND NOT granted AND $2 = ANY(pg_blocking_pids($1))
"""
# The relation locks a backend holds that an INSERT's RowExclusiveLock waits
# for (the PostgreSQL conflict table). The backfill must hold none of them.
_CONFLICTS_WITH_INSERT = """
SELECT mode, relation::regclass::text AS relation
FROM pg_locks
WHERE pid = $1 AND granted AND locktype = 'relation'
  AND mode IN ('ShareLock', 'ShareRowExclusiveLock', 'ExclusiveLock', 'AccessExclusiveLock')
"""
# What a failure needs to name the culprit: everything the writer is queued
# on, who it waits for and what they are, and what the backfill holds.
_WRITER_WAITS = """
SELECT locktype, mode, relation::regclass::text AS relation
FROM pg_locks WHERE pid = $1 AND NOT granted
"""
_BLOCKERS = """
SELECT pid, backend_type, application_name, left(query, 200) AS query
FROM pg_stat_activity WHERE pid = ANY(pg_blocking_pids($1))
"""
_HELD = """
SELECT locktype, mode, relation::regclass::text AS relation
FROM pg_locks WHERE pid = $1 AND granted
"""
_WRITER_ROWS = "SELECT COUNT(*) FROM agent_events WHERE time >= $1"


def _turn(session: str, n: int, model: str) -> Row:
    payload = json.dumps(
        {"model": model, "input_tokens": 10 + n % 7, "output_tokens": 1, "cache_read_tokens": n}
    )
    return Row(_T0 + timedelta(seconds=n), TOKEN_USAGE, session, f"exec-{session}", payload)


def _summary(session: str, n: int) -> Row:
    payload = json.dumps(
        {
            "model": _MODELS[n % 2],
            "total_input_tokens": 1_000 + n,
            "total_output_tokens": 10,
            "cache_read_tokens": 5_000,
            "total_cost_usd": 0.01 * (n % 9),
        }
    )
    return Row(
        _T0 + timedelta(hours=1, seconds=n), SESSION_SUMMARY, session, f"exec-{session}", payload
    )


def _history() -> list[Row]:
    rows: list[Row] = []
    for s in range(HISTORY_SESSIONS):
        session = f"hist-{s:04d}"
        rows.append(Row(_T0, SESSION_STARTED, session, f"exec-{session}", "{}"))
        rows.extend(_turn(session, i, _MODELS[i % 2]) for i in range(TURNS_PER_SESSION))
        if s % 2:
            rows.append(_summary(session, s))
    return rows


@dataclass
class Writer:
    """Inserts one event at a time, each committed on its own, until told to stop."""

    dsn: str
    stop: asyncio.Event = field(default_factory=asyncio.Event)
    live: asyncio.Event = field(default_factory=asyncio.Event)
    pid: int | None = None
    """Its backend, so the test can ask pg_locks what it is waiting on."""
    committed: int = 0

    def _next(self, i: int) -> Row:
        # Alternate between sessions early and late in the backfill's order,
        # and new sessions, on the same model keys the history uses.
        if i % 3 == 0:
            session = f"hist-{i % HISTORY_SESSIONS:04d}"
        elif i % 3 == 1:
            session = f"hist-{HISTORY_SESSIONS - 1 - i % HISTORY_SESSIONS:04d}"
        else:
            session = f"live-{i % 17}"
        if i % 11 == 0:
            return _summary(session, 10_000 + i)
        return _turn(session, 10_000 + i, _MODELS[i % 2])

    async def run(self) -> None:
        import asyncpg

        conn = await asyncpg.connect(self.dsn)
        try:
            self.pid = conn.get_server_pid()
            while not self.stop.is_set():
                await copy_rows(conn, [self._next(self.committed)])
                self.committed += 1
                if self.committed >= LIVE_INSERTS:
                    self.live.set()
                await asyncio.sleep(0.002)
        finally:
            await conn.close()


_TURN_DIFF = """
WITH raw AS (
    SELECT session_id, execution_id, data->>'model' AS model,
        data->>'requested_model' AS requested_model, (data ? 'requested_model') AS has_rm,
        SUM(COALESCE((data->>'input_tokens')::bigint, 0)) AS i,
        SUM(COALESCE((data->>'output_tokens')::bigint, 0)) AS o,
        SUM(COALESCE((data->>'cache_creation_tokens')::bigint, 0)) AS cc,
        SUM(COALESCE((data->>'cache_read_tokens')::bigint, 0)) AS cr,
        COUNT(*) AS n
    FROM agent_events WHERE event_type = 'token_usage'
    GROUP BY 1, 2, 3, 4, 5
), rolled AS (
    SELECT session_id, execution_id, model, requested_model, has_requested_model AS has_rm,
        SUM(input_tokens) AS i, SUM(output_tokens) AS o,
        SUM(cache_creation_tokens) AS cc, SUM(cache_read_tokens) AS cr,
        SUM(observations) AS n
    FROM agent_turn_usage_rollup
    GROUP BY 1, 2, 3, 4, 5
)
SELECT
    (SELECT COUNT(*) FROM (SELECT * FROM raw EXCEPT SELECT * FROM rolled) a) AS missing,
    (SELECT COUNT(*) FROM (SELECT * FROM rolled EXCEPT SELECT * FROM raw) b) AS extra,
    (SELECT COUNT(*) FROM raw) AS keys
"""

_SUMMARY_DIFF = """
WITH raw AS (
    SELECT session_id, execution_id, time, data->>'model' AS model,
        (data->>'total_cost_usd')::numeric AS cost,
        COALESCE((data->>'total_input_tokens')::bigint, 0) AS i
    FROM agent_events WHERE event_type = 'session_summary'
), rolled AS (
    SELECT session_id, execution_id, time, model, vendor_cost_usd AS cost, input_tokens AS i
    FROM agent_summary_usage
)
SELECT
    (SELECT COUNT(*) FROM (SELECT * FROM raw EXCEPT ALL SELECT * FROM rolled) a) AS missing,
    (SELECT COUNT(*) FROM (SELECT * FROM rolled EXCEPT ALL SELECT * FROM raw) b) AS extra,
    (SELECT COUNT(*) FROM raw) AS rows
"""


async def _assert_rollup_equals_raw(conn: asyncpg.Connection) -> tuple[int, int]:
    turns = await conn.fetchrow(_TURN_DIFF)
    summaries = await conn.fetchrow(_SUMMARY_DIFF)
    assert turns is not None and summaries is not None
    assert (turns["missing"], turns["extra"]) == (0, 0), dict(turns)
    assert (summaries["missing"], summaries["extra"]) == (0, 0), dict(summaries)
    return int(turns["keys"]), int(summaries["rows"])


async def _until_committed(writer: Writer, writing: asyncio.Task[None], target: int) -> None:
    """Wait for the writer to reach ``target`` commits, failing if it dies first."""
    try:
        async with asyncio.timeout(HANG_GUARD_S):
            while writer.committed < target:
                if writing.done():
                    writing.result()  # the writer died: raise its error
                    pytest.fail("the writer stopped before it was told to")
                await asyncio.sleep(POLL_S)
    except TimeoutError:
        pytest.fail(f"the writer committed {writer.committed} of {target} inserts, then hung")


async def _until_parked(
    gate: asyncpg.Connection, backfill_pid: int, migrating: asyncio.Task[None]
) -> None:
    """Wait for the backfill to block on the gate, inside its first batch."""
    try:
        async with asyncio.timeout(HANG_GUARD_S):
            while not await gate.fetchval(_PARKED_AT_GATE, backfill_pid):
                if migrating.done():
                    migrating.result()
                    pytest.fail("ensure_schema finished without running a backfill batch")
                await asyncio.sleep(POLL_S)
    except TimeoutError:
        pytest.fail("ensure_schema never reached the backfill")


async def _lock_report(gate: asyncpg.Connection, writer_pid: int, backfill_pid: int) -> str:
    """Who the writer waits on and what the backfill holds, for a failure message."""
    waits = [dict(r) for r in await gate.fetch(_WRITER_WAITS, writer_pid)]
    blockers = [dict(r) for r in await gate.fetch(_BLOCKERS, writer_pid)]
    held = [dict(r) for r in await gate.fetch(_HELD, backfill_pid)]
    return (
        f"writer {writer_pid} waits on {waits}, blocked by {blockers}; "
        f"backfill {backfill_pid} holds {held}"
    )


async def _commits_while_parked(
    gate: asyncpg.Connection, writer: Writer, writing: asyncio.Task[None], backfill_pid: int
) -> None:
    """PARKED_INSERTS more commits, with the writer never queued behind the backfill.

    A backfill holding a lock that conflicts with INSERT keeps it until the
    gate opens, so the conflict is in pg_locks however fast or slow the
    runner is: checked once up front, then on every wait the writer is in.
    """
    assert writer.pid is not None
    conflicts = await gate.fetch(_CONFLICTS_WITH_INSERT, backfill_pid)
    assert not conflicts, (
        "the backfill, parked inside a batch, holds a lock every insert waits for: "
        f"{[dict(c) for c in conflicts]}; {await _lock_report(gate, writer.pid, backfill_pid)}"
    )
    target = writer.committed + PARKED_INSERTS
    try:
        async with asyncio.timeout(HANG_GUARD_S):
            while writer.committed < target:
                waits = await gate.fetch(_WAITING_ON_BACKFILL, writer.pid, backfill_pid)
                assert not waits, (
                    "an insert is queued behind the backfill, which is parked inside a "
                    f"batch: {[dict(w) for w in waits]}; "
                    f"{await _lock_report(gate, writer.pid, backfill_pid)}"
                )
                if writing.done():
                    writing.result()
                    pytest.fail("the writer stopped before it was told to")
                await asyncio.sleep(POLL_S)
    except TimeoutError:
        pytest.fail(
            f"the writer committed {writer.committed} of {target} inserts, then hung: "
            f"{await _lock_report(gate, writer.pid, backfill_pid)}"
        )


async def test_inserts_flow_during_the_backfill_and_each_is_counted_once(
    test_infrastructure, monkeypatch: pytest.MonkeyPatch
) -> None:
    import asyncpg

    from syn_adapters.events import schema
    from syn_adapters.events.schema import EventStoreSchema

    monkeypatch.setattr(schema, "USAGE_ROLLUP_BACKFILL_BATCH_SESSIONS", BATCH_SESSIONS)
    monkeypatch.setattr(
        schema, "USAGE_ROLLUP_BACKFILL_SQL", (*schema.USAGE_ROLLUP_BACKFILL_SQL, _GATE_SQL)
    )

    async with throwaway_database(test_infrastructure.timescaledb_url) as dsn:
        await prepare_pre_e1_schema(dsn)
        conn = await asyncpg.connect(dsn)
        gate = await asyncpg.connect(dsn)
        writer = Writer(dsn)
        writing: asyncio.Task[None] | None = None
        migrating: asyncio.Task[None] | None = None
        try:
            await copy_rows(conn, _history())
            await conn.execute("ANALYZE agent_events")
            await gate.execute("SELECT pg_advisory_lock($1, $2)", *_GATE)

            # The writer is live before the rollup exists.
            writing = asyncio.create_task(writer.run())
            await _until_committed(writer, writing, LIVE_INSERTS)

            migrating = asyncio.create_task(EventStoreSchema().ensure_schema(conn))
            await _until_parked(gate, conn.get_server_pid(), migrating)

            # 1. Ingest carries on while a backfill batch is open.
            await _commits_while_parked(gate, writer, writing, conn.get_server_pid())
            assert not migrating.done()
            assert await gate.fetchval(_PARKED_AT_GATE, conn.get_server_pid()), (
                "the backfill left the gate while the test held it"
            )
            # Read the count first: the writer keeps committing while the query is
            # in flight, so a count compared with a later read can fall short.
            committed = writer.committed
            assert await gate.fetchval(_WRITER_ROWS, _WRITER_T0) >= committed, (
                "the writer's inserts are not visible to another session: not committed"
            )

            await gate.execute("SELECT pg_advisory_unlock($1, $2)", *_GATE)
            async with asyncio.timeout(HANG_GUARD_S):
                await migrating
            await _until_committed(writer, writing, writer.committed + AFTER_INSERTS)
            writer.stop.set()
            await writing

            # 2. Exactly once, against a fresh aggregation of everything written.
            keys, summaries = await _assert_rollup_equals_raw(conn)
            assert keys > HISTORY_SESSIONS and summaries > HISTORY_SESSIONS // 2

            # And a re-run converges instead of adding.
            await EventStoreSchema.backfill_usage_rollup(conn)
            await _assert_rollup_equals_raw(conn)
        finally:
            writer.stop.set()
            await gate.close()  # opens the gate, if a failure left it shut
            for task in (migrating, writing):
                if task is not None and not task.done():
                    task.cancel()
                    with contextlib.suppress(asyncio.CancelledError, Exception):
                        await task
            await conn.close()
