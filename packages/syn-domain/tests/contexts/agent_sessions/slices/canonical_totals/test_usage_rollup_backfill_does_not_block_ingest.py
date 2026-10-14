"""The usage rollup's backfill neither pauses ingest nor miscounts it (#1558 r2).

The first version created the trigger and ran the whole backfill in ONE
transaction. CREATE TRIGGER takes SHARE ROW EXCLUSIVE on agent_events, which
conflicts with every INSERT, so ingest stopped for the length of a full scan
of the usage events, at every first deploy and every reconcile.

Now the trigger commits first and the backfill runs afterwards in batches,
under no lock an insert waits on. Two claims, both tested here against a
real database:

  1. NO INSERT WAITS ON THE BACKFILL. Just before every batch commits, with
     every statement run and so every lock it will take still held, inserts
     into that batch's own sessions must commit from another connection
     under ``lock_timeout``. Those sessions were given a trigger-written row
     on every model before the first batch, so each probe UPDATEs a row that
     existed when the batch ran. A backfill that held a lock an insert
     conflicts with (a table lock, the trigger DDL, a row lock on the
     trigger's rollup rows) makes the probe wait, the wait hits the
     timeout, and the test names the locks the backfill held. Every batch
     must be probed, each in a transaction of its own (distinct txids), so
     one long transaction across the batches fails too.

     This used to be a RATE: inserts completed during the backfill, as a
     fraction of the writer's free-running rate (#1860). A shared runner
     made that a flake (#1952: 4 inserts in 740 ms against 178/s). Blocking
     is a lock conflict, not a speed, so the test now asks Postgres directly
     whether the insert can get its locks while the backfill holds its own.
     ``lock_timeout`` counts only lock waits, so a slow runner cannot fail
     it, and the background writer never runs concurrently with a probe, so
     the only lock a probe can wait on is the backfill's.
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
    from types import TracebackType

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
# A watchdog, not a bound under test: a backfill wedged on a lock must fail
# the test rather than hang the job.
ENSURE_SCHEMA_TIMEOUT_S = 600.0
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
    """Inserts one event at a time until told to stop: ingest, running throughout.

    Each insert holds ``turn``, which the probe takes too, so a probe never
    queues behind a writer insert on the same session's rows: a probe that
    waits, waits on the backfill.
    """

    dsn: str
    turn: asyncio.Lock = field(default_factory=asyncio.Lock)
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
                async with self.turn:
                    await copy_rows(conn, [self._next(self.inserted)])
                self.inserted += 1
                if self.inserted >= WRITER_WARMUP_INSERTS:
                    self.warmed_up.set()
                await asyncio.sleep(0.002)
        finally:
            await conn.close()


@dataclass
class Probe:
    """Inserts into a batch's own sessions just before that batch commits."""

    conn: asyncpg.Connection
    writer: Writer
    sessions_listed: int = 0
    seeded: int = 0
    transactions: list[int] = field(default_factory=list)
    _n: int = 0

    def _rows(self, sessions: list[str]) -> list[Row]:
        rows: list[Row] = []
        for session in sessions:
            for model in _MODELS:
                self._n += 1
                rows.append(_turn(session, 20_000 + self._n, model))
        return rows

    async def _insert(self, rows: list[Row]) -> None:
        """One COPY, never queued behind the writer, bounded on every wait."""
        await asyncio.wait_for(self.writer.turn.acquire(), timeout=PROBE_HARD_TIMEOUT_S)
        try:
            await asyncio.wait_for(copy_rows(self.conn, rows), timeout=PROBE_HARD_TIMEOUT_S)
        finally:
            self.writer.turn.release()

    async def seed(self, sessions: list[str]) -> None:
        """Give every session a TRIGGER-written row on every model, before any batch.

        The trigger only ever updates its own rows (``backfilled = FALSE``),
        so a probe into a key with no such row inserts a fresh one and could
        not notice a backfill that row-locked the trigger's rows. Seeded here,
        after the trigger is live and before the first batch, every probe
        updates a row that existed when its batch ran.
        """
        rows = self._rows(sessions)
        await self._insert(rows)
        self.seeded = len(rows)

    async def before_commit(self, backfill: asyncpg.Connection, batch: list[str]) -> None:
        import asyncpg

        # Every statement of the batch has run and COMMIT has not: the batch
        # holds every lock it will ever take. Its advisory lock and its own
        # transaction id prove the open transaction is this batch's alone.
        assert backfill.is_in_transaction(), "the probe must run inside the batch"
        pid = backfill.get_server_pid()
        assert await self.conn.fetchval(_HOLDS_ADVISORY_SQL, pid) is True, (
            "the backfill's batch transaction is not holding its schema lock"
        )
        self.transactions.append(int(await backfill.fetchval("SELECT txid_current()")))
        try:
            await self._insert(self._rows(batch))
        except (asyncpg.exceptions.LockNotAvailableError, TimeoutError):
            held: list[str] = []
            with contextlib.suppress(Exception):
                records = await asyncio.wait_for(
                    self.conn.fetch(_HELD_LOCKS_SQL, pid), timeout=PROBE_HARD_TIMEOUT_S
                )
                held = [f"{r['locktype']} {r['relation']} {r['mode']}" for r in records]
            pytest.fail(
                f"an insert into {batch} waited on the backfill's open batch transaction "
                f"(lock_timeout {PROBE_LOCK_TIMEOUT}); the backfill held: " + "; ".join(held)
            )
        assert backfill.is_in_transaction(), "the batch committed before the probe returned"


class _ProbedTransaction:
    """The batch's transaction, probing on a clean exit just before COMMIT."""

    def __init__(self, inner: Transaction, conn: _ProbedConnection) -> None:
        self._inner = inner
        self._conn = conn

    async def __aenter__(self) -> None:
        await self._inner.__aenter__()
        self._conn.batch = None

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        batch, self._conn.batch = self._conn.batch, None
        if exc_type is None and batch is not None:
            try:
                await self._conn.probe.before_commit(self._conn.inner, batch)
            except BaseException as err:
                await self._inner.__aexit__(type(err), err, err.__traceback__)
                raise
        await self._inner.__aexit__(exc_type, exc, tb)


class _ProbedConnection:
    """The backfill's connection, seeding before the first batch, probing each one.

    Delegates exactly what backfill_usage_rollup uses, so a change to that
    surface fails loudly here instead of silently skipping the probe.
    """

    def __init__(self, inner: asyncpg.Connection, probe: Probe) -> None:
        self.inner = inner
        self.probe = probe
        self.batch: list[str] | None = None

    async def fetch(self, query: str, *args: object) -> list[asyncpg.Record]:
        from syn_adapters.events import schema

        rows = await self.inner.fetch(query, *args)
        if query == schema.USAGE_ROLLUP_BACKFILL_SESSIONS_SQL:
            self.probe.sessions_listed = len(rows)
            await self.probe.seed([str(r["session_id"]) for r in rows])
        return rows

    def transaction(self) -> _ProbedTransaction:
        return _ProbedTransaction(self.inner.transaction(), self)

    async def execute(self, query: str, *args: object) -> str:
        from syn_adapters.events import schema

        result = await self.inner.execute(query, *args)
        if query in schema.USAGE_ROLLUP_BACKFILL_SQL:
            self.batch = cast("list[str]", args[0])
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
            writer = Writer(dsn)
            probe = Probe(probe_conn, writer)

            async def probed(
                backfill: asyncpg.Connection, *, batch_sessions: int | None = None
            ) -> None:
                proxy = cast("asyncpg.Connection", _ProbedConnection(backfill, probe))
                await unprobed(proxy, batch_sessions=batch_sessions)

            monkeypatch.setattr(EventStoreSchema, "backfill_usage_rollup", staticmethod(probed))

            await copy_rows(conn, _history())
            await conn.execute("ANALYZE agent_events")

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
                await asyncio.wait_for(
                    EventStoreSchema().ensure_schema(conn), timeout=ENSURE_SCHEMA_TIMEOUT_S
                )
            finally:
                await _stop(writer, writing)
            if writing.done() and not writing.cancelled():
                writing.result()  # the writer died mid-backfill: raise its error

            # 1. Every batch was probed, each in a transaction of its own, so
            # no batch held a lock an insert needs, at the moment it held most.
            assert probe.sessions_listed >= HISTORY_SESSIONS
            assert probe.seeded == probe.sessions_listed * len(_MODELS)
            batches = -(-probe.sessions_listed // BATCH_SESSIONS)
            assert len(probe.transactions) == batches, (
                f"{len(probe.transactions)} of {batches} backfill batches were probed; "
                "the backfill no longer runs the statements this test hooks"
            )
            assert len(set(probe.transactions)) == batches, (
                "backfill batches shared a transaction, so their locks outlive a batch"
            )
            print(f"\n{batches} batches each let an insert commit before they did")

            # 2. Exactly once, against a fresh aggregation of everything written.
            keys, summaries = await _assert_rollup_equals_raw(conn)
            assert keys > HISTORY_SESSIONS and summaries > HISTORY_SESSIONS // 2

            # And a re-run converges instead of adding.
            await unprobed(conn)
            await _assert_rollup_equals_raw(conn)
        finally:
            await probe_conn.close()
            await conn.close()
