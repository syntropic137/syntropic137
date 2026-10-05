"""One workflow's executions, read from the real Postgres projection store (#1558).

``get_by_workflow_id`` used to read every execution and filter in Python;
/metrics?workflow_id= calls it twice per request, which is what kept the E1
latency gate over budget on CI. It now filters in the store. The unit tests
cover the filter against an in-memory store; this pins the two things only
Postgres can show: the SQL predicate returns exactly one workflow's rows, and
the expression index exists and is one the planner can use for it.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING
from urllib.parse import urlsplit, urlunsplit

import asyncpg
import pytest

from syn_adapters.projection_stores.postgres_store import PostgresProjectionStore
from syn_domain.contexts.orchestration.slices.list_executions.projection import (
    WorkflowExecutionListProjection,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

pytestmark = pytest.mark.integration

TABLE = WorkflowExecutionListProjection.PROJECTION_NAME
INDEX = f"idx_{TABLE}_workflow_id"


@pytest.fixture
async def pool(test_infrastructure) -> AsyncIterator[asyncpg.Pool]:
    """A pool on a database of its own, dropped afterwards."""
    admin_url = test_infrastructure.timescaledb_url
    name = f"by_workflow_{uuid.uuid4().hex[:12]}"
    admin = await asyncpg.connect(admin_url)
    await admin.execute(f'CREATE DATABASE "{name}"')
    parts = urlsplit(admin_url)
    created = await asyncpg.create_pool(urlunsplit(parts._replace(path=f"/{name}")))
    assert created is not None
    try:
        yield created
    finally:
        await created.close()
        await admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        await admin.close()


async def _save(
    store: PostgresProjectionStore, execution_id: str, workflow_id: str | None, started_at: str
) -> None:
    record = {"execution_id": execution_id, "workflow_name": "w", "status": "completed"}
    record["started_at"] = started_at
    if workflow_id is not None:
        record["workflow_id"] = workflow_id
    await store.save(TABLE, execution_id, record)


async def test_returns_exactly_one_workflows_executions_newest_first(
    pool: asyncpg.Pool,
) -> None:
    store = PostgresProjectionStore(pool)
    await _save(store, "exec-1", "wf-a", "2026-10-01T09:00:00Z")
    await _save(store, "exec-2", "wf-a", "2026-10-01T10:00:00Z")
    await _save(store, "exec-3", "wf-b", "2026-10-01T11:00:00Z")
    # A prefix of the wanted id, and a row from before the field existed:
    # neither is "wf-a".
    await _save(store, "exec-4", "wf-a-2", "2026-10-01T12:00:00Z")
    await _save(store, "exec-5", None, "2026-10-01T13:00:00Z")

    executions = await WorkflowExecutionListProjection(store).get_by_workflow_id("wf-a")

    assert [e.workflow_execution_id for e in executions] == ["exec-2", "exec-1"]


async def test_the_workflow_filter_has_an_index_the_planner_can_use(pool: asyncpg.Pool) -> None:
    store = PostgresProjectionStore(pool)
    await _save(store, "exec-1", "wf-a", "2026-10-01T09:00:00Z")

    async with pool.acquire() as conn:
        assert await conn.fetchval("SELECT to_regclass($1) IS NOT NULL", INDEX)
        # One row cannot make an index scan the cheapest plan, so take the
        # alternative away: what is left proves the index matches the predicate.
        await conn.execute("SET enable_seqscan = off")
        plan = "\n".join(
            row[0]
            for row in await conn.fetch(
                f"EXPLAIN SELECT data FROM {TABLE} WHERE data->>'workflow_id' = $1", "wf-a"
            )
        )
    assert INDEX in plan, plan
