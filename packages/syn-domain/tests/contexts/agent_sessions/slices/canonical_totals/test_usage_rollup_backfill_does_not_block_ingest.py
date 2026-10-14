"""The usage rollup's backfill neither pauses ingest nor miscounts it (#1558 r2).

The first version created the trigger and ran the whole backfill in ONE
transaction. CREATE TRIGGER takes SHARE ROW EXCLUSIVE on agent_events, which
conflicts with every INSERT, so ingest stopped for the length of a full scan
of the usage events, at every first deploy and every reconcile.

Now the trigger commits first and the backfill runs afterwards in batches,
under no lock an insert waits on. Two claims, both tested here against a
real database:

  1. NO INSERT WAITS ON THE BACKFILL. At the end of every batch, with the
     batch's transaction still open and therefore still holding every lock
     it took, an insert into one of the batch's own sessions must commit
     from another connection under ``lock_timeout``. A backfill that held a
     lock an insert conflicts with (a table lock, the trigger DDL, a row lock
     on the rollup) makes that insert wait, the wait hits the timeout, and
     the test names the locks the backfill was holding.

     This used to be a RATE: inserts completed during the backfill, as a
     fraction of the writer's free-running rate (#1860). A shared runner
     made that a flake (#1952: 4 inserts in 740 ms against 178/s). Blocking
     is a lock conflict, not a speed, so the test now asks Postgres directly
     whether the insert can get its locks while the backfill holds its own.
     ``lock_timeout`` counts only lock waits, so a slow runner cannot fail it.
  2. EVERY EVENT IS COUNTED EXACTLY ONCE. After the dust settles, the rollup
     equals a fresh aggregation of agent_events: per turn key (every token
     column and the observation count) and per summary row (as a multiset).
     A concurrent writer hits sessions the backfill has already passed,
     sessions it has not reached yet, and brand-new ones, on the same model
     keys the backfill writes, and every probe in claim 1 lands in a session
     whose batch has read its snapshot but not yet committed, so a missed or
     doubled event shows up.

MARKED ``integration``: CI runs it on push to main, PRs into release and the
weekly cron, not on PRs into main.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, cast

import pytest

from syn_shared.events import SESSION_STARTED, SESSION_SUMMARY, TOKEN_USAGE

from .usage_rollup_seed import Row, copy_rows, prepare_pre_e1_schema, throwaway_database

if TYPE_CHECKING:
    import asyncpg
    from asyncpg.transaction import Transaction

pytestmark = pytest.mark.integration

HISTORY_SESSIONS = 300
TURNS_PER_SESSION = 200
BATCH_SESSIONS = 5  # many short transactions, so there are many to probe
WRITER_WARMUP_INSERTS = 3  # the writer is live before the backfill starts
WRITER_WARMUP_TIMEOUT_S = 30.0  # generous: connection setup on a slow runner is not the test
# How long a probe insert may WAIT ON A LOCK. Not a speed bound: an insert
# that is not blocked waits zero, and one that is blocked waits until the
# backfill batch commits, which never happens while the probe holds it open.
PROBE_LOCK_TIMEOUT = "5s"
# Belt and braces only: lock_timeout ends a blocked probe long before this.
PROBE_HARD_TIMEOUT_S = 60.0
_MODELS = ("claude-sonnet-5", "claude-haiku-4-5-20251001")
_T0 = datetime(2026, 9, 1, tzinfo=UTC)

_HELD_LOCKS_SQL = """
SELECT locktype, COALESCE(relation::regclass::text, '') AS relation, mode
FROM pg_locks
WHERE pid = $1 AND granted
ORDER BY locktype, relation, mode
"""
_HOLDS_ADVISORY_SQL = """
SELECT EXISTS (
    SELECT 1 FROM pg_locks WHERE pid = $1 AND locktype = 'advisory' AND granted
)
"""


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
    """Inserts one event at a time until told to stop: ingest, running throughout."""

    dsn: str
    stop: asyncio.Event = field(default_factory=asyncio.Event)
    warmed_up: asyncio.Event = field(default_factory=asyncio.Event)
    inserted: int = 0

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
            while not self.stop.is_set():
                await copy_rows(conn, [self._next(self.inserted)])
                self.inserted += 1
                if self.inserted >= WRITER_WARMUP_INSERTS:
                    self.warmed_up.set()
                await asyncio.sleep(0.002)
        finally:
            await conn.close()


@dataclass
class Probe:
    """Inserts into a batch's own session while that batch's transaction is open."""

    conn: asyncpg.Connection
    probed: int = 0
    sessions_listed: int = 0

    async def during_batch(self, backfill: asyncpg.Connection, batch: list[str]) -> None:
        import asyncpg

        # The batch has run every statement and not committed: it holds every
        # lock it will take, and its advisory lock proves the transaction is
        # the backfill's and is open right now.
        assert backfill.is_in_transaction(), "the probe must run inside the batch"
        pid = backfill.get_server_pid()
        assert await self.conn.fetchval(_HOLDS_ADVISORY_SQL, pid) is True, (
            "the backfill's batch transaction is not holding its schema lock"
        )
        n = 20_000 + self.probed
        row = _turn(batch[0], n, _MODELS[n % 2])
        try:
            await asyncio.wait_for(copy_rows(self.conn, [row]), timeout=PROBE_HARD_TIMEOUT_S)
        except (asyncpg.exceptions.LockNotAvailableError, TimeoutError):
            held = await self.conn.fetch(_HELD_LOCKS_SQL, pid)
            pytest.fail(
                f"an insert into {batch[0]} waited on the backfill's batch transaction "
                f"(lock_timeout {PROBE_LOCK_TIMEOUT}); the backfill held: "
                + "; ".join(f"{r['locktype']} {r['relation']} {r['mode']}" for r in held)
            )
        assert backfill.is_in_transaction(), "the batch committed before the probe returned"
        self.probed += 1


class _ProbedConnection:
    """The backfill's connection, probing after each batch's last statement.

    Delegates exactly what backfill_usage_rollup uses, so a change to that
    surface fails loudly here instead of silently skipping the probe.
    """

    def __init__(self, inner: asyncpg.Connection, probe: Probe) -> None:
        self._inner = inner
        self._probe = probe

    async def fetch(self, query: str, *args: object) -> list[asyncpg.Record]:
        from syn_adapters.events import schema

        rows = await self._inner.fetch(query, *args)
        if query == schema.USAGE_ROLLUP_BACKFILL_SESSIONS_SQL:
            self._probe.sessions_listed = len(rows)
        return rows

    def transaction(self) -> Transaction:
        return self._inner.transaction()

    async def execute(self, query: str, *args: object) -> str:
        from syn_adapters.events import schema

        result = await self._inner.execute(query, *args)
        if query == schema.USAGE_ROLLUP_BACKFILL_SQL[-1]:
            batch = cast("list[str]", args[0])
            await self._probe.during_batch(self._inner, batch)
        return result


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


async def _stop(writer: Writer, writing: asyncio.Task[None]) -> None:
    writer.stop.set()
    # A stuck writer must not outlive the test: a bounded chance, then cancel.
    with contextlib.suppress(asyncio.CancelledError, TimeoutError):
        await asyncio.wait_for(writing, timeout=PROBE_HARD_TIMEOUT_S)


async def test_inserts_flow_during_the_backfill_and_each_is_counted_once(
    test_infrastructure, monkeypatch: pytest.MonkeyPatch
) -> None:
    import asyncpg

    from syn_adapters.events import schema
    from syn_adapters.events.schema import EventStoreSchema

    monkeypatch.setattr(schema, "USAGE_ROLLUP_BACKFILL_BATCH_SESSIONS", BATCH_SESSIONS)
    unprobed = EventStoreSchema.backfill_usage_rollup

    async with throwaway_database(test_infrastructure.timescaledb_url) as dsn:
        await prepare_pre_e1_schema(dsn)
        conn = await asyncpg.connect(dsn)
        probe_conn = await asyncpg.connect(dsn)
        try:
            await probe_conn.execute(f"SET lock_timeout = '{PROBE_LOCK_TIMEOUT}'")
            probe = Probe(probe_conn)

            async def probed(
                backfill: asyncpg.Connection, *, batch_sessions: int | None = None
            ) -> None:
                proxy = cast("asyncpg.Connection", _ProbedConnection(backfill, probe))
                await unprobed(proxy, batch_sessions=batch_sessions)

            monkeypatch.setattr(EventStoreSchema, "backfill_usage_rollup", staticmethod(probed))

            await copy_rows(conn, _history())
            await conn.execute("ANALYZE agent_events")

            writer = Writer(dsn)
            writing = asyncio.create_task(writer.run())
            warm = asyncio.create_task(writer.warmed_up.wait())
            done, _ = await asyncio.wait(
                {warm, writing},
                timeout=WRITER_WARMUP_TIMEOUT_S,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if warm not in done:
                warm.cancel()
                if writing in done:
                    writing.result()  # the writer died: raise its error
                await _stop(writer, writing)
                pytest.fail(
                    f"the writer completed {writer.inserted} of {WRITER_WARMUP_INSERTS} "
                    f"warm-up inserts in {WRITER_WARMUP_TIMEOUT_S:.0f} s"
                )

            try:
                await EventStoreSchema().ensure_schema(conn)
            finally:
                await _stop(writer, writing)
            if writing.done() and not writing.cancelled():
                writing.result()  # the writer died mid-backfill: raise its error

            # 1. Every batch was probed, so no batch held a lock an insert needs.
            assert probe.sessions_listed >= HISTORY_SESSIONS
            batches = -(-probe.sessions_listed // BATCH_SESSIONS)
            assert probe.probed == batches, (
                f"{probe.probed} of {batches} backfill batches were probed; "
                "the backfill no longer runs the statements this test hooks"
            )
            print(f"\n{probe.probed} batches each let an insert commit while still open")

            # 2. Exactly once, against a fresh aggregation of everything written.
            keys, summaries = await _assert_rollup_equals_raw(conn)
            assert keys > HISTORY_SESSIONS and summaries > HISTORY_SESSIONS // 2

            # And a re-run converges instead of adding.
            await unprobed(conn)
            await _assert_rollup_equals_raw(conn)
        finally:
            await probe_conn.close()
            await conn.close()
