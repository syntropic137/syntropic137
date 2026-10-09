"""``newest_per_group``: both stores pick the same newest document per group.

The rule (``syn_domain.projection_newest``): newest by the PARSED instant, so
an offset decides nothing; ties to the lowest key; undated rows, rows whose
flag reads false and rows with no group are never candidates; only the listed
fields come back. The in-memory store is held to it in the unit run and the
Postgres store, on the same cases, in the integration run.
"""

from __future__ import annotations

import os

os.environ.setdefault("APP_ENVIRONMENT", "test")

import uuid
from typing import TYPE_CHECKING
from urllib.parse import urlsplit, urlunsplit

import asyncpg
import pytest

from syn_adapters.projection_stores.memory_store import InMemoryProjectionStore
from syn_adapters.projection_stores.postgres_scan import build_newest_per_group_query
from syn_adapters.projection_stores.postgres_store import PostgresProjectionStore

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Mapping

    from syn_domain.projection_newest import ProjectionNewestPerGroup
    from syn_domain.projection_scan import JsonValue

PROJECTION = "newest_per_group_cases"

ROWS: list[tuple[str, dict[str, JsonValue]]] = [
    # 08:00 UTC, though its text sorts after the 09:00 UTC row below.
    ("a-offset", {"g": "plan", "at": "2026-10-01T10:00:00+02:00", "w": "wf", "body": "x"}),
    ("b-utc", {"g": "plan", "at": "2026-10-01T09:00:00+00:00", "w": "wf", "body": "x"}),
    # The same instant twice: the lower key wins.
    ("d-tie", {"g": "review", "at": "2026-10-01T12:00:00+02:00", "w": "wf", "body": "x"}),
    ("c-tie", {"g": "review", "at": "2026-10-01T10:00:00Z", "w": "wf", "body": "x"}),
    # Newer, but flagged false / undated / another workflow / no group.
    ("e-flag", {"g": "review", "at": "2026-10-02T00:00:00Z", "w": "wf", "ok": False}),
    ("f-undated", {"g": "ship", "at": None, "w": "wf"}),
    ("g-other", {"g": "plan", "at": "2026-10-05T00:00:00Z", "w": "wf-2"}),
    ("h-nogroup", {"at": "2026-10-05T00:00:00Z", "w": "wf"}),
    # A non-boolean flag reads as true; no offset reads as UTC.
    ("i-strflag", {"g": "ship2", "at": "2026-10-01 10:00:00", "w": "wf", "ok": "false"}),
]

EXPECTED = {"plan": "b-utc", "review": "c-tie", "ship2": "i-strflag"}


async def _answer(store: ProjectionNewestPerGroup) -> Mapping[str, Mapping[str, JsonValue]]:
    return await store.newest_per_group(
        PROJECTION,
        group_field="g",
        timestamp_field="at",
        fields=("id", "g", "missing"),
        filters={"w": "wf"},
        flag_field="ok",
    )


async def _seed(store: InMemoryProjectionStore | PostgresProjectionStore) -> None:
    for key, row in ROWS:
        await store.save(PROJECTION, key, {"id": key, **row})


def _check(answer: Mapping[str, Mapping[str, JsonValue]]) -> None:
    assert {group: row["id"] for group, row in answer.items()} == EXPECTED
    for row in answer.values():
        assert set(row) == {"id", "g", "missing"}
        assert row["missing"] is None


@pytest.mark.unit
async def test_in_memory_store_picks_the_newest_instant_per_group() -> None:
    store = InMemoryProjectionStore()
    await _seed(store)
    _check(await _answer(store))


@pytest.mark.unit
async def test_a_group_filter_narrows_to_the_listed_groups() -> None:
    store = InMemoryProjectionStore()
    await _seed(store)
    answer = await store.newest_per_group(
        PROJECTION,
        group_field="g",
        timestamp_field="at",
        fields=("id",),
        filters={"w": "wf", "g": ["plan"]},
    )
    assert {group: row["id"] for group, row in answer.items()} == {"plan": "b-utc"}


@pytest.mark.unit
def test_the_sql_orders_by_instant_then_key_and_never_by_text() -> None:
    query, params = build_newest_per_group_query(
        "artifact_summaries",
        group_field="phase_id",
        timestamp_field="created_at",
        fields=("id",),
        filters={"workflow_id": "wf"},
        flag_field="is_primary_deliverable",
        lean_ready=True,
    )
    assert "ORDER BY data->>'phase_id', syn_page_instant_v1(data->>'created_at') DESC, id" in query
    assert "data->>'created_at' DESC" not in query
    assert "COALESCE(lean, data)" in query
    assert params == ["wf"]


@pytest.mark.unit
def test_the_sql_refuses_an_unsafe_field() -> None:
    with pytest.raises(ValueError, match="unsafe"):
        build_newest_per_group_query(
            "t",
            group_field="g'; drop",
            timestamp_field="at",
            fields=(),
            filters=None,
            flag_field=None,
            lean_ready=False,
        )


@pytest.fixture
async def pool(test_infrastructure) -> AsyncIterator[asyncpg.Pool]:
    """A pool on a database of its own, dropped afterwards."""
    admin_url = test_infrastructure.timescaledb_url
    name = f"newest_{uuid.uuid4().hex[:12]}"
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


@pytest.mark.integration
async def test_postgres_store_picks_the_same_newest_per_group(pool: asyncpg.Pool) -> None:
    store = PostgresProjectionStore(pool)
    await _seed(store)
    _check(await _answer(store))


@pytest.mark.integration
async def test_postgres_artifacts_answer_without_their_bodies(pool: asyncpg.Pool) -> None:
    """The artifact table's lean column is what is read: the body never comes back."""
    from syn_domain.contexts.artifacts.slices.list_artifacts.projection import (
        ArtifactListProjection,
    )

    projection = ArtifactListProjection(PostgresProjectionStore(pool))
    for artifact_id, at in (("old", "2026-10-01T10:00:00+02:00"), ("new", "2026-10-01T09:00:00Z")):
        await projection.on_artifact_created(
            {
                "artifact_id": artifact_id,
                "workflow_id": "wf",
                "phase_id": "plan",
                "artifact_type": "document",
                "title": artifact_id,
                "content": "body",
                "created_at": at,
                "is_primary_deliverable": True,
            }
        )
    latest = await projection.latest_deliverables("wf", ["plan", "review"])
    assert {phase: s.id for phase, s in latest.items()} == {"plan": "new"}
    assert latest["plan"].content is None
    assert latest["plan"].size_bytes == 4
