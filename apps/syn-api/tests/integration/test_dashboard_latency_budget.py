"""Latency gate: the dashboard's slow endpoints stay inside a p95 budget (E1).

The owner, twice: "Pages are taking way too long ... over 1000ms ... heatmap
takes even longer". Measured live: /metrics 1.9s, /metrics?workflow_id= 3.0s,
/insights/contribution-heatmap 2.0-4.1s.

WHAT IS TIMED. The real endpoints, end to end: an HTTP request through the
FastAPI app (routing, wiring, every read the route makes, serialization),
against a real TimescaleDB holding both stores the routes read in production
(ADR-030, one database): the observability hypertable (Lane 2) and the
Postgres projection store (Lane 1 read models). Only the event-store gRPC
client is in-memory, and none of these routes reads it.

    GET /metrics
    GET /metrics?workflow_id=<a workflow with 20 executions>
    GET /insights/contribution-heatmap?metric=sessions   (the dashboard's call)

WHY IT IS AN INTEGRATION TEST, NOT A ci/fitness TEST. Everything under
ci/fitness/ is static analysis with no database. A p95 needs a live
TimescaleDB, so it lives here, under the `integration` marker, on the shared
test_infrastructure fixture (env vars, test-stack on 15432, or
testcontainers). It runs in its own throwaway database so a re-run, or a run
of main after a run of this branch, starts from the same empty schema.

WHERE CI RUNS IT. The `python-integration-tests` job in ci.yml runs
`pytest -m integration` over the repo testpaths (this file included) on
pushes to main, PRs into `release`, the weekly cron and manual dispatch. It
does NOT run on PRs into main: that tiering is deliberate and is the job's
`if:`, not something this file can change.

THE DATASET is shaped like the live install, scaled down so it seeds in
seconds: 2,000 executions in 100 workflows, each with a session carrying 40
turns, a summary on 4 in 5, and 120 tool observations, spread over ninety
days - 322k observability rows. Turns and tool observations are the rows the
old reads scaled with.

THE BUDGET is set from measurement on the CI image (timescale 2.29.2-pg16),
on an Apple M-series laptop with Docker Desktop:

    endpoint                         origin/main p95   this branch p95
    /metrics                         see PR #1558 for the pasted tables
    /metrics?workflow_id=
    /insights/contribution-heatmap

The E1 target is 300ms p95. The branch sits well under it, so 300ms leaves
headroom for a slower CI runner, while main is over it by a margin no runner
variance explains: a regression back to a whole-history scan fails here.
"""

from __future__ import annotations

import json
import math
import os
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from urllib.parse import urlsplit, urlunsplit

import asyncpg
import httpx
import pytest

from syn_shared.events import GIT_COMMIT, SESSION_STARTED, SESSION_SUMMARY, TOKEN_USAGE

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

pytestmark = pytest.mark.integration

os.environ.setdefault("APP_ENVIRONMENT", "test")

EXECUTIONS = 2_000
EXECUTIONS_PER_WORKFLOW = 20
TURNS_PER_SESSION = 40
TOOL_EVENTS_PER_SESSION = 120
DAYS = 90
RUNS = 20
WARMUP = 2

GATED_WORKFLOW = "wf-0"

# p95 per endpoint, in milliseconds. The E1 target; see the module docstring
# for the measurements it was checked against.
BUDGET_MS = 300.0

ENDPOINTS: tuple[tuple[str, str, dict[str, str]], ...] = (
    ("/metrics", "/metrics", {}),
    ("/metrics?workflow_id=", "/metrics", {"workflow_id": GATED_WORKFLOW}),
    ("/insights/contribution-heatmap", "/insights/contribution-heatmap", {"metric": "sessions"}),
)

_COLUMNS = ("time", "event_type", "session_id", "execution_id", "phase_id", "data")
_Row = tuple[datetime, str, str, str, str, str]


def _execution(n: int) -> str:
    return f"exec-{n}"


def _workflow(n: int) -> str:
    return f"wf-{n // EXECUTIONS_PER_WORKFLOW}"


def _rows(now: datetime) -> list[_Row]:
    """The seeded observability rows, deterministic so every run times the same work."""
    rows: list[_Row] = []
    for n in range(EXECUTIONS):
        execution = _execution(n)
        session = f"sess-{n}"
        start = now - timedelta(days=n % DAYS, minutes=n % 600)
        model = ("claude-sonnet-5", "claude-haiku-4-5-20251001")[n % 2]

        def at(i: int, start: datetime = start) -> datetime:
            return start + timedelta(seconds=i)

        rows.append((at(0), SESSION_STARTED, session, execution, "p1", "{}"))
        turn = json.dumps(
            {"model": model, "input_tokens": 100, "output_tokens": 1, "cache_read_tokens": 900}
        )
        rows.extend(
            (at(1 + i), TOKEN_USAGE, session, execution, "p1", turn)
            for i in range(TURNS_PER_SESSION)
        )
        for i in range(TOOL_EVENTS_PER_SESSION):
            tool = json.dumps({"tool_name": "Bash", "tool_use_id": f"t{i}", "output": "x" * 200})
            rows.append((at(100 + i), "tool_execution_completed", session, execution, "p1", tool))
        if n % 3 == 0:
            commit = json.dumps({"sha": f"{n}"})
            rows.append((at(300), GIT_COMMIT, session, execution, "p1", commit))
        # Most sessions finish; the rest are priced from their turns.
        if n % 5:
            summary = json.dumps(
                {
                    "model": model,
                    "total_input_tokens": 4_000,
                    "total_output_tokens": 900,
                    "cache_read_tokens": 36_000,
                    "total_cost_usd": 0.05,
                }
            )
            rows.append((at(400), SESSION_SUMMARY, session, execution, "p1", summary))
    return rows


def _with_database(url: str, name: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, f"/{name}", "", ""))


@pytest.fixture
async def gate_database(test_infrastructure) -> AsyncIterator[str]:
    """An empty database of its own, dropped afterwards."""
    admin_url = test_infrastructure.timescaledb_url
    name = f"latency_gate_{uuid.uuid4().hex[:12]}"
    admin = await asyncpg.connect(admin_url)
    try:
        await admin.execute(f'CREATE DATABASE "{name}"')
    finally:
        await admin.close()
    try:
        yield _with_database(admin_url, name)
    finally:
        admin = await asyncpg.connect(admin_url)
        try:
            await admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        finally:
            await admin.close()


async def _seed_projections() -> None:
    """Executions in the read model, so /metrics?workflow_id= resolves real ids."""
    from syn_api._wiring import get_projection_mgr

    executions = get_projection_mgr().workflow_execution_list
    for n in range(EXECUTIONS):
        await executions.on_workflow_execution_started(
            {
                "execution_id": _execution(n),
                "workflow_id": _workflow(n),
                "workflow_name": _workflow(n),
                "started_at": "2026-09-25T00:00:00+00:00",
                "total_phases": 1,
            }
        )


@pytest.fixture
async def app_on_seeded_postgres(
    gate_database: str, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[httpx.AsyncClient]:
    """The real app, wired to a seeded TimescaleDB for both stores it reads."""
    from syn_adapters import projection_stores
    from syn_adapters.events import AgentEventStore, store_helpers
    from syn_adapters.projection_stores import PostgresProjectionStore
    from syn_adapters.projections.manager import reset_projection_manager
    from syn_api.main import create_app

    store = AgentEventStore(gate_database)
    await store.initialize()
    pool = store.pool
    assert pool is not None
    monkeypatch.setattr(store_helpers, "_event_store", store)
    monkeypatch.setattr(projection_stores, "_store_instance", PostgresProjectionStore(pool))
    reset_projection_manager()

    async with pool.acquire() as conn:
        # COPY, as insert_batch does in production, so any trigger on
        # agent_events sees these rows exactly the way it sees real ones.
        now = datetime.now(UTC).replace(microsecond=0)
        await conn.copy_records_to_table("agent_events", records=_rows(now), columns=_COLUMNS)
    await _seed_projections()
    async with pool.acquire() as conn:
        await conn.execute("ANALYZE")

    try:
        transport = httpx.ASGITransport(app=create_app())
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            yield client
    finally:
        reset_projection_manager()
        await store.close()


async def _p95_ms(client: httpx.AsyncClient, path: str, params: dict[str, str]) -> float:
    for _ in range(WARMUP):
        (await client.get(path, params=params)).raise_for_status()
    samples: list[float] = []
    for _ in range(RUNS):
        started = time.perf_counter()
        response = await client.get(path, params=params)
        samples.append((time.perf_counter() - started) * 1000)
        response.raise_for_status()
    samples.sort()
    return samples[math.ceil(0.95 * len(samples)) - 1]


async def test_dashboard_endpoints_stay_inside_their_p95_budget(
    app_on_seeded_postgres: httpx.AsyncClient,
) -> None:
    client = app_on_seeded_postgres

    # The gate must be timing real work, not an empty table or an error body.
    scoped = (await client.get("/metrics", params={"workflow_id": GATED_WORKFLOW})).json()
    assert scoped["total_sessions"] == EXECUTIONS_PER_WORKFLOW, scoped
    assert scoped["total_tokens"] > 0, scoped
    everything = (await client.get("/metrics")).json()
    assert everything["total_sessions"] == EXECUTIONS, everything
    heatmap = await client.get("/insights/contribution-heatmap", params={"metric": "sessions"})
    assert heatmap.json()["total"] == EXECUTIONS, heatmap.text

    measured = {name: await _p95_ms(client, path, params) for name, path, params in ENDPOINTS}

    table = "\n".join(f"  {name:<32} p95 {ms:7.1f} ms" for name, ms in measured.items())
    print(f"\nlatency gate (budget {BUDGET_MS:.0f}ms p95, {RUNS} runs):\n{table}")
    over = {name: ms for name, ms in measured.items() if ms > BUDGET_MS}
    assert not over, f"p95 over the {BUDGET_MS:.0f}ms budget:\n{table}"
