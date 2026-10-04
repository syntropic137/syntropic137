"""Latency gate: the dashboard's usage reads stay inside a p95 budget (E1).

The owner, twice: "Pages are taking way too long ... over 1000ms ... heatmap
takes even longer". Measured live: /metrics 1.9s, /metrics?workflow_id= 3.0s,
/insights/contribution-heatmap 2.0-4.1s. Each of those is dominated by one
observability read, and those reads are what this gate times:

    /metrics                        CanonicalUsageQueryService.totals()
    /metrics?workflow_id=           CanonicalUsageQueryService.totals(execution_ids)
    /insights/contribution-heatmap  TimescaleHeatmapQuery.query(365-day window)

The endpoint's other reads (projection-store rows, the execution list) are
small and constant and are not what made the page slow, so they are not timed.

WHY IT IS AN INTEGRATION TEST, NOT A ci/fitness TEST. Everything under
ci/fitness/ is static analysis with no database. A p95 needs a live
TimescaleDB, so it lives here, under the `integration` marker, and uses the
shared test_infrastructure fixture (test-stack, CI's service on 15432, or
testcontainers). CI runs `-m integration` on pushes to main, the weekly cron
and PRs into `release` - not on PRs into main.

THE DATASET is shaped like the live install, scaled down so it seeds in
seconds: thousands of executions, each with a session carrying dozens of turns,
a summary, and a hundred-odd tool observations, spread over ninety days. Turns
and tool observations are the rows the old reads scaled with.

THE BUDGET. Target <= 300ms p95. Set from measurement - see BUDGET_MS.
"""

from __future__ import annotations

import json
import math
import time
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from syn_shared.events import GIT_COMMIT, SESSION_STARTED, SESSION_SUMMARY, TOKEN_USAGE

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Awaitable, Callable

    import asyncpg

pytestmark = pytest.mark.integration

PREFIX = "latency-gate-e1-"
EXECUTIONS = 2_000
EXECUTIONS_PER_WORKFLOW = 20
TURNS_PER_SESSION = 40
TOOL_EVENTS_PER_SESSION = 120
DAYS = 90
RUNS = 20
WARMUP = 2

# p95 per read, in milliseconds. The E1 target is 300ms; see the module
# docstring and the PR for the measurements these were set from.
BUDGET_MS = 300.0

_COLUMNS = ("time", "event_type", "session_id", "execution_id", "phase_id", "data")
_Row = tuple[datetime, str, str, str, str, str]


def _execution(n: int) -> str:
    return f"{PREFIX}exec-{n}"


def _rows() -> list[_Row]:
    """The seeded dataset, deterministic so every run times the same work."""
    now = datetime.now(UTC).replace(microsecond=0)
    rows: list[_Row] = []
    for n in range(EXECUTIONS):
        execution = _execution(n)
        session = f"{PREFIX}sess-{n}"
        start = now - timedelta(days=n % DAYS, minutes=n % 600)
        model = ("claude-sonnet-5", "claude-haiku-4-5-20251001")[n % 2]

        def at(i: int, start: datetime = start) -> datetime:
            return start + timedelta(seconds=i)

        rows.append((at(0), SESSION_STARTED, session, execution, "p1", "{}"))
        for i in range(TURNS_PER_SESSION):
            data = {
                "model": model,
                "input_tokens": 100,
                "output_tokens": 1,
                "cache_read_tokens": 900,
            }
            rows.append((at(1 + i), TOKEN_USAGE, session, execution, "p1", json.dumps(data)))
        for i in range(TOOL_EVENTS_PER_SESSION):
            data = {"tool_name": "Bash", "tool_use_id": f"t{i}", "output": "x" * 200}
            rows.append(
                (
                    at(100 + i),
                    "tool_execution_completed",
                    session,
                    execution,
                    "p1",
                    json.dumps(data),
                )
            )
        if n % 3 == 0:
            rows.append(
                (at(300), GIT_COMMIT, session, execution, "p1", json.dumps({"sha": f"{n}"}))
            )
        # Most sessions finish; the rest are priced from their turns.
        if n % 5:
            summary = {
                "model": model,
                "total_input_tokens": 4_000,
                "total_output_tokens": 900,
                "cache_read_tokens": 36_000,
                "total_cost_usd": 0.05,
            }
            rows.append((at(400), SESSION_SUMMARY, session, execution, "p1", json.dumps(summary)))
    return rows


async def _forget(conn: asyncpg.pool.PoolConnectionProxy) -> None:
    pattern = f"{PREFIX}%"
    await conn.execute("DELETE FROM agent_events WHERE session_id LIKE $1", pattern)
    for table in ("agent_event_day_rollup", "agent_summary_usage", "agent_turn_usage_rollup"):
        if await conn.fetchval("SELECT to_regclass($1) IS NOT NULL", table):
            await conn.execute(f"DELETE FROM {table} WHERE session_id LIKE $1", pattern)


@pytest.fixture
async def seeded_pool(test_infrastructure) -> AsyncGenerator[asyncpg.Pool, None]:
    from syn_adapters.events import AgentEventStore

    store = AgentEventStore(test_infrastructure.timescaledb_url)
    await store.initialize()
    pool = store.pool
    assert pool is not None
    async with pool.acquire() as conn:
        await _forget(conn)
        # COPY, as insert_batch does in production, so the rollup triggers see
        # these rows exactly the way they see real ones.
        await conn.copy_records_to_table("agent_events", records=_rows(), columns=_COLUMNS)
        await conn.execute("ANALYZE")
    try:
        yield pool
    finally:
        async with pool.acquire() as conn:
            await _forget(conn)
        await store.close()


async def _p95_ms(read: Callable[[], Awaitable[object]]) -> float:
    for _ in range(WARMUP):
        await read()
    samples: list[float] = []
    for _ in range(RUNS):
        started = time.perf_counter()
        await read()
        samples.append((time.perf_counter() - started) * 1000)
    samples.sort()
    return samples[math.ceil(0.95 * len(samples)) - 1]


async def test_dashboard_usage_reads_stay_inside_their_p95_budget(
    seeded_pool: asyncpg.Pool,
) -> None:
    from syn_domain.contexts.agent_sessions import CanonicalUsageQueryService, CostCalculator
    from syn_domain.contexts.organization.slices.contribution_heatmap.TimescaleHeatmapQuery import (
        TimescaleHeatmapQuery,
    )

    totals = CanonicalUsageQueryService(seeded_pool, CostCalculator())
    heatmap = TimescaleHeatmapQuery(seeded_pool)
    one_workflow = {_execution(n) for n in range(EXECUTIONS_PER_WORKFLOW)}
    today = datetime.now(UTC).date()
    year_ago: date = today - timedelta(days=364)

    reads: dict[str, Callable[[], Awaitable[object]]] = {
        "/metrics": totals.totals,
        "/metrics?workflow_id=": lambda: totals.totals(execution_ids=one_workflow),
        "/insights/contribution-heatmap": lambda: heatmap.query(year_ago, today),
    }
    measured = {name: await _p95_ms(read) for name, read in reads.items()}

    # The gate must be timing real work, not an empty table.
    seeded_totals = await totals.totals(execution_ids=one_workflow)
    assert seeded_totals.sessions == EXECUTIONS_PER_WORKFLOW
    assert seeded_totals.total_tokens > 0

    report = ", ".join(f"{name} p95={ms:.0f}ms" for name, ms in measured.items())
    print(f"latency gate (budget {BUDGET_MS:.0f}ms): {report}")
    over = {name: ms for name, ms in measured.items() if ms > BUDGET_MS}
    assert not over, f"p95 over the {BUDGET_MS:.0f}ms budget: {report}"
