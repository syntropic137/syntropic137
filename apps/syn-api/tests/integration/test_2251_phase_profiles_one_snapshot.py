"""GET /metrics/phase-profiles is read from ONE snapshot, never from two (#2251).

``PhaseProfileQueryService.profiles`` reads token aggregates, then resource
aggregates, on one connection. At READ COMMITTED each statement takes its own
snapshot, so a phase committed between them shows up in the resources and not
the tokens.

The test pauses the read after its token statement, commits a new phase with
tokens and a resource-usage row from a second connection, lets the read
finish, and asserts the HTTP response equals the one read before the commit or
the one read after it. The commit is checked to change BOTH halves, so a mixed
response cannot equal either.
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable

    import asyncpg
    import httpx

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

WORKFLOW = "wf-snapshot"
MODEL = "claude-sonnet-5"
EXECUTIONS = 3
_COLUMNS = ("time", "event_type", "session_id", "execution_id", "phase_id", "data")
_Row = tuple[datetime, str, str, str, str, str]


def _phase_rows(execution: str, phase: str, start: datetime) -> list[_Row]:
    session = f"{execution}-{phase}"
    summary = {
        "model": MODEL,
        "total_input_tokens": 1000,
        "total_output_tokens": 10,
        "cache_creation_tokens": 0,
        "cache_read_tokens": 0,
        "total_cost_usd": 0.01,
    }
    usage = {
        "cpu_usage_seconds": 6.0,
        "cpu_throttled_seconds": 0.0,
        "memory_peak_bytes": 1 << 20,
        "disk_bytes_at_teardown": 1 << 20,
        "workspace_lifetime_seconds": 60.0,
    }
    return [
        (start, "session_started", session, execution, phase, "{}"),
        (start + timedelta(seconds=60), "session_summary", session, execution, phase,
         json.dumps(summary)),
        (start + timedelta(seconds=60), "workspace_resource_usage", session, execution, phase,
         json.dumps(usage)),
    ]  # fmt: skip


async def _copy(pool: asyncpg.Pool, rows: list[_Row]) -> None:
    """Commit through COPY, the way production writes, so the rollup trigger sees it."""
    async with pool.acquire() as conn:
        await conn.copy_records_to_table("agent_events", records=rows, columns=_COLUMNS)


class _PausingConnection:
    """A pooled connection that runs ``between`` after its first ``fetch``; else the real one."""

    def __init__(
        self, conn: asyncpg.pool.PoolConnectionProxy, between: Callable[[], Awaitable[None]]
    ) -> None:
        self._conn = conn
        self._between = between
        self.paused = False

    def __getattr__(self, name: str) -> object:
        return getattr(self._conn, name)

    async def fetch(self, query: str, *args: object) -> list[asyncpg.Record]:
        rows = await self._conn.fetch(query, *args)
        if not self.paused:
            self.paused = True
            await self._between()
        return rows


class _PausingPool:
    def __init__(self, pool: asyncpg.Pool, between: Callable[[], Awaitable[None]]) -> None:
        self._pool = pool
        self._between = between
        self.connection: _PausingConnection | None = None

    @asynccontextmanager
    async def acquire(self) -> AsyncIterator[_PausingConnection]:
        async with self._pool.acquire() as conn:
            self.connection = _PausingConnection(conn, self._between)
            yield self.connection


@pytest.fixture
async def seeded(
    e2_database: str, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[tuple[httpx.AsyncClient, asyncpg.Pool, datetime]]:
    import httpx

    from syn_adapters import projection_stores
    from syn_adapters.events import AgentEventStore, store_helpers
    from syn_adapters.projection_stores import PostgresProjectionStore, get_projection_store
    from syn_adapters.projections.manager import reset_projection_manager
    from syn_api.main import create_app
    from syn_domain.contexts.orchestration.slices.list_executions.projection import (
        WorkflowExecutionListProjection,
    )

    store = AgentEventStore(e2_database)
    await store.initialize()
    pool = store.pool
    assert pool is not None
    monkeypatch.setattr(store_helpers, "_event_store", store)
    monkeypatch.setattr(projection_stores, "_store_instance", PostgresProjectionStore(pool))
    reset_projection_manager()
    now = datetime.now(UTC).replace(microsecond=0)
    listing = WorkflowExecutionListProjection(get_projection_store())
    rows: list[_Row] = []
    for i in range(EXECUTIONS):
        execution, start = f"exec-{i}", now - timedelta(hours=i + 1)
        await listing.on_workflow_execution_started(
            {
                "execution_id": execution,
                "workflow_id": WORKFLOW,
                "workflow_name": WORKFLOW,
                "started_at": start.isoformat(),
                "total_phases": 2,
                "inputs": {},
            }
        )
        rows += _phase_rows(execution, "plan", start)
    await _copy(pool, rows)
    try:
        transport = httpx.ASGITransport(app=create_app())
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            yield client, pool, now
    finally:
        reset_projection_manager()
        await store.close()


async def _profiles(client: httpx.AsyncClient) -> tuple[str, str]:
    """The response's token half and resource half, each as canonical JSON."""
    response = await client.get("/metrics/phase-profiles", params={"workflow_id": WORKFLOW})
    assert response.status_code == 200, response.text
    body = response.json()
    return (
        json.dumps(body["tokens"], sort_keys=True),
        json.dumps(body["resources"], sort_keys=True),
    )


async def test_tokens_and_resources_are_one_snapshot(
    seeded: tuple[httpx.AsyncClient, asyncpg.Pool, datetime], monkeypatch: pytest.MonkeyPatch
) -> None:
    from syn_api.routes import metrics
    from syn_domain.contexts.agent_sessions import CostCalculator
    from syn_domain.contexts.orchestration import PhaseProfileQueryService

    client, pool, now = seeded
    before = await _profiles(client)

    # A new phase of an existing execution, with tokens AND a resource row,
    # committed after the token read and before the resource read.
    paused = _PausingPool(
        pool, lambda: _copy(pool, _phase_rows("exec-0", "review", now - timedelta(minutes=30)))
    )
    real = metrics.get_phase_profile_query
    monkeypatch.setattr(
        metrics,
        "get_phase_profile_query",
        lambda: PhaseProfileQueryService(paused, CostCalculator()),  # type: ignore[arg-type]  # a pool double
    )
    during = await _profiles(client)
    # Not monkeypatch.undo(): that would also unwire the fixture's stores.
    monkeypatch.setattr(metrics, "get_phase_profile_query", real)

    assert paused.connection is not None and paused.connection.paused
    after = await _profiles(client)
    # The commit moved both halves, so a response mixing them equals neither side.
    assert before[0] != after[0]
    assert before[1] != after[1]
    assert during in {before, after}
