"""The usage rollup's backfill neither pauses ingest nor miscounts it (#1558 r2).

The first version created the trigger and ran the whole backfill in ONE
transaction. CREATE TRIGGER takes SHARE ROW EXCLUSIVE on agent_events, which
conflicts with every INSERT, so ingest stopped for the length of a full scan
of the usage events, at every first deploy and every reconcile.

Now the trigger commits first and the backfill runs afterwards in batches,
under no lock an insert waits on. Two claims, both tested here against a
real database with a writer inserting the whole time:

  1. INGEST CARRIES ON. Inserts complete while the backfill is running, and
     none of them waits anywhere near as long as the backfill takes.
  2. EVERY EVENT IS COUNTED EXACTLY ONCE. After the dust settles, the rollup
     equals a fresh aggregation of agent_events: per turn key (every token
     column and the observation count) and per summary row (as a multiset).
     The concurrent writer hits sessions the backfill has already passed,
     sessions it has not reached yet, and brand-new ones, on the same model
     keys the backfill writes, so a missed or doubled event shows up.

MARKED ``integration``: CI runs it on push to main, PRs into release and the
weekly cron, not on PRs into main.
"""

from __future__ import annotations

import asyncio
import json
import time
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
TURNS_PER_SESSION = 200
BATCH_SESSIONS = 5  # many short transactions, so the writer interleaves with them
_MODELS = ("claude-sonnet-5", "claude-haiku-4-5-20251001")
_T0 = datetime(2026, 9, 1, tzinfo=UTC)


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
    """Inserts one event at a time until told to stop, timing each insert."""

    dsn: str
    stop: asyncio.Event = field(default_factory=asyncio.Event)
    finished_at: list[float] = field(default_factory=list)
    latencies: list[float] = field(default_factory=list)

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
            i = 0
            while not self.stop.is_set():
                started = time.perf_counter()
                await copy_rows(conn, [self._next(i)])
                now = time.perf_counter()
                self.latencies.append(now - started)
                self.finished_at.append(now)
                i += 1
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


async def test_inserts_flow_during_the_backfill_and_each_is_counted_once(
    test_infrastructure, monkeypatch: pytest.MonkeyPatch
) -> None:
    import asyncpg

    from syn_adapters.events import schema
    from syn_adapters.events.schema import EventStoreSchema

    monkeypatch.setattr(schema, "USAGE_ROLLUP_BACKFILL_BATCH_SESSIONS", BATCH_SESSIONS)

    async with throwaway_database(test_infrastructure.timescaledb_url) as dsn:
        await prepare_pre_e1_schema(dsn)
        conn = await asyncpg.connect(dsn)
        try:
            await copy_rows(conn, _history())
            await conn.execute("ANALYZE agent_events")

            writer = Writer(dsn)
            writing = asyncio.create_task(writer.run())
            await asyncio.sleep(0.2)  # the writer is live before the rollup exists

            started = time.perf_counter()
            await EventStoreSchema().ensure_schema(conn)
            ended = time.perf_counter()

            await asyncio.sleep(0.2)
            writer.stop.set()
            await writing

            backfill_s = ended - started
            during = [t for t in writer.finished_at if started < t < ended]
            worst = max(
                lat
                for lat, t in zip(writer.latencies, writer.finished_at, strict=True)
                if t > started
            )
            print(
                f"\nbackfill {backfill_s * 1000:.0f} ms over {HISTORY_SESSIONS} sessions in "
                f"batches of {BATCH_SESSIONS}; {len(during)} inserts completed during it; "
                f"worst insert latency {worst * 1000:.0f} ms"
            )

            # 1. Ingest carried on. A backfill holding inserts off would let
            # none complete inside its window, and its last waiter would have
            # waited about as long as the backfill itself.
            assert len(during) >= 20, f"only {len(during)} inserts completed during the backfill"
            assert worst < backfill_s / 2, (
                f"an insert waited {worst * 1000:.0f} ms of a {backfill_s * 1000:.0f} ms backfill"
            )

            # 2. Exactly once, against a fresh aggregation of everything written.
            keys, summaries = await _assert_rollup_equals_raw(conn)
            assert keys > HISTORY_SESSIONS and summaries > HISTORY_SESSIONS // 2

            # And a re-run converges instead of adding.
            await EventStoreSchema.backfill_usage_rollup(conn)
            await _assert_rollup_equals_raw(conn)
        finally:
            await conn.close()
