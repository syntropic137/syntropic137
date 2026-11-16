"""``GET /workflows?order_by=`` pages are cut from one ordered collection in Postgres (#1843).

The workflow list hands ``order_by`` to ``ProjectionStore.query``, which orders
the whole filtered collection before the page is cut. Postgres used to order on
``data->>'field'``, which is text, so ``-runs_count`` put 9 ahead of 10 there and
behind it in the in-memory store. This holds the real Postgres store to the
same pages as the in-memory one, for every sortable field in both directions,
and to the numeric order the dashboard's "top workflows by runs" depends on.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from urllib.parse import urlsplit, urlunsplit

import asyncpg
import pytest

os.environ.setdefault("APP_ENVIRONMENT", "test")

from syn_adapters.projection_stores.memory_store import InMemoryProjectionStore
from syn_adapters.projection_stores.postgres_store import PostgresProjectionStore
from syn_domain.contexts.orchestration.domain.read_models import WorkflowSummary
from syn_domain.contexts.orchestration.slices.list_workflows.projection import (
    SORTABLE_FIELDS,
    WorkflowListProjection,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from event_sourcing import ProjectionStore

pytestmark = pytest.mark.integration

PAGE_SIZE = 2

# (name, workflow_type, runs, phases); created oldest first, two per day so
# created_at ties too. 10 against 9 is the pair a text order gets backwards.
_SEED = [
    ("Echo", "custom", 10, 9),
    ("Bravo", "research", 9, 10),
    ("Golf", "custom", 2, 1),
    ("Alpha", "research", 9, 2),
    ("Foxtrot", "custom", 1, 9),
    ("Charlie", "research", 3, 3),
    ("Delta", "custom", 9, 1),
]


@pytest.fixture
async def pool(test_infrastructure) -> AsyncIterator[asyncpg.Pool]:
    """A pool on a database of its own, dropped afterwards."""
    admin_url = test_infrastructure.timescaledb_url
    name = f"workflow_order_{uuid.uuid4().hex[:12]}"
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


async def _seed(store: ProjectionStore) -> WorkflowListProjection:
    for i, (name, kind, runs, phases) in enumerate(_SEED):
        summary = WorkflowSummary(
            id=f"wf-{i:02d}",
            name=name,
            workflow_type=kind,
            classification="simple",
            phase_count=phases,
            description=None,
            created_at=datetime(2026, 1, i // 2 + 1, tzinfo=UTC),
            runs_count=runs,
        )
        await store.save(WorkflowListProjection.PROJECTION_NAME, summary.id, summary.to_dict())
    return WorkflowListProjection(store)


async def _walk(projection: WorkflowListProjection, order_by: str) -> list[list[str]]:
    pages: list[list[str]] = []
    for offset in range(0, len(_SEED), PAGE_SIZE):
        rows = await projection.query(order_by=order_by, offset=offset, limit=PAGE_SIZE)
        pages.append([row.id for row in rows])
    return pages


async def test_postgres_pages_are_the_in_memory_pages(pool: asyncpg.Pool) -> None:
    in_sql = await _seed(PostgresProjectionStore(pool))
    in_memory = await _seed(InMemoryProjectionStore())

    for field in sorted(SORTABLE_FIELDS):
        for order_by in (field, f"-{field}"):
            pages = await _walk(in_sql, order_by)
            flat = [i for page in pages for i in page]
            assert sorted(flat) == [f"wf-{i:02d}" for i in range(len(_SEED))], (order_by, pages)
            assert pages == await _walk(in_memory, order_by), order_by


async def test_most_runs_first_is_numeric_and_ties_break_by_id(pool: asyncpg.Pool) -> None:
    projection = await _seed(PostgresProjectionStore(pool))

    assert await _walk(projection, "-runs_count") == [
        ["wf-00", "wf-01"],
        ["wf-03", "wf-06"],
        ["wf-05", "wf-02"],
        ["wf-04"],
    ]
    assert await _walk(projection, "-phase_count") == [
        ["wf-01", "wf-00"],
        ["wf-04", "wf-05"],
        ["wf-03", "wf-02"],
        ["wf-06"],
    ]
