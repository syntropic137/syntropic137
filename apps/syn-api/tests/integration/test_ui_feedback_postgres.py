"""UI feedback against a real PostgreSQL (ADR-016, #105).

The flag-level behaviour is pinned by ``test_ui_feedback_feature_flag.py``,
which needs no infrastructure. What only a real database can show is here:

* with the flag off, a database that the API has booted against still has
  no feedback tables in it;
* with the flag on, the schema is applied at startup, converges when
  applied again, and a full item - screenshot included - survives the
  round trip through the API and comes back out of the filters an agent
  triages with.

Each test gets its own database, so "no tables" means no tables rather
than "none that a previous run left behind".
"""

from __future__ import annotations

import io
import os
import uuid
from contextlib import contextmanager
from typing import TYPE_CHECKING
from urllib.parse import urlsplit, urlunsplit

import asyncpg
import httpx
import pytest

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator

pytestmark = pytest.mark.integration


os.environ.setdefault("APP_ENVIRONMENT", "test")


@contextmanager
def configured(*, enabled: bool, db_url: str) -> Iterator[None]:
    """Run a block against a specific feature configuration."""
    from syn_api.services import ui_feedback
    from syn_shared.settings import reset_settings

    previous = {
        key: os.environ.get(key) for key in ("SYN_UI_FEEDBACK_ENABLED", "SYN_OBSERVABILITY_DB_URL")
    }
    os.environ["SYN_UI_FEEDBACK_ENABLED"] = "true" if enabled else "false"
    os.environ["SYN_OBSERVABILITY_DB_URL"] = db_url
    reset_settings()
    ui_feedback.reset_for_tests()
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        reset_settings()
        ui_feedback.reset_for_tests()


def _with_database(url: str, name: str) -> str:
    """Point a Postgres URL at a different database on the same server."""
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, f"/{name}", "", ""))


@pytest.fixture
async def ephemeral_database(test_infrastructure) -> AsyncIterator[str]:
    """An empty database of its own, dropped afterwards."""
    admin_url = test_infrastructure.timescaledb_url
    name = f"ui_feedback_test_{uuid.uuid4().hex[:12]}"

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


async def _table_exists(url: str, table: str) -> bool:
    conn = await asyncpg.connect(url)
    try:
        return bool(await conn.fetchval("SELECT to_regclass($1) IS NOT NULL", table))
    finally:
        await conn.close()


async def test_disabled_startup_leaves_the_database_untouched(ephemeral_database: str):
    """Off is the open-source posture: the migration must not run at all."""
    from syn_api.services import ui_feedback

    with configured(enabled=False, db_url=ephemeral_database):
        await ui_feedback.connect()
        try:
            assert await _table_exists(ephemeral_database, "feedback_items") is False
            assert await _table_exists(ephemeral_database, "feedback_media") is False
        finally:
            await ui_feedback.disconnect()


async def test_enabled_startup_applies_the_schema_idempotently(ephemeral_database: str):
    """Runs on an empty database and again on an already-migrated one."""
    from syn_api.services import ui_feedback

    with configured(enabled=True, db_url=ephemeral_database):
        await ui_feedback.connect()
        await ui_feedback.disconnect()
        ui_feedback.reset_for_tests()

        assert await _table_exists(ephemeral_database, "feedback_items") is True

        # Second boot against a database that already has the schema.
        await ui_feedback.connect()
        try:
            assert await _table_exists(ephemeral_database, "feedback_media") is True
        finally:
            await ui_feedback.disconnect()


async def test_round_trip_through_the_api(ephemeral_database: str):
    """Create with a screenshot, filter the list, move the status on."""
    from syn_api.main import create_app
    from syn_api.services import ui_feedback

    with configured(enabled=True, db_url=ephemeral_database):
        await ui_feedback.connect()
        try:
            transport = httpx.ASGITransport(app=create_app())
            async with httpx.AsyncClient(
                transport=transport, base_url="http://testserver"
            ) as client:
                await _assert_round_trip(client)
        finally:
            await ui_feedback.disconnect()


async def _assert_round_trip(client: httpx.AsyncClient) -> None:
    """Use the test's event loop for both asyncpg and ASGI requests."""
    assert (await client.get("/features")).json() == {"ui_feedback": True}

    created = await client.post(
        "/feedback",
        json={
            "url": "http://localhost:9137/executions/exec-1",
            "route": "/executions/exec-1",
            "subject_kind": "execution",
            "subject_id": "exec-1",
            "feedback_type": "bug",
            "comment": "The phase timer keeps running after it finishes.",
            "app_name": "syn-dashboard-ui",
        },
    )
    assert created.status_code == 201, created.text
    feedback_id = created.json()["id"]

    png = b"\x89PNG\r\n\x1a\n" + b"0" * 1024
    uploaded = await client.post(
        f"/feedback/{feedback_id}/media",
        files={"file": ("shot.png", io.BytesIO(png), "image/png")},
        data={"media_type": "screenshot"},
    )
    assert uploaded.status_code == 201, uploaded.text
    media_id = uploaded.json()["id"]

    # The bytes come back, not just the row.
    downloaded = await client.get(f"/feedback/{feedback_id}/media/{media_id}")
    assert downloaded.status_code == 200
    assert downloaded.content == png

    # Filterable by the things an agent triages on.
    by_route = (await client.get("/feedback", params={"route": "/executions/exec-1"})).json()
    assert [item["id"] for item in by_route["items"]] == [feedback_id]
    assert by_route["items"][0]["media_count"] == 1

    assert (await client.get("/feedback", params={"subject_id": "exec-1"})).json()["total"] == 1
    assert (await client.get("/feedback", params={"subject_id": "other"})).json()["total"] == 0
    assert (await client.get("/feedback", params={"type": "bug"})).json()["total"] == 1
    assert (await client.get("/feedback", params={"created_after": "2999-01-01T00:00:00Z"})).json()[
        "total"
    ] == 0

    patched = await client.patch(f"/feedback/{feedback_id}", json={"status": "resolved"})
    assert patched.status_code == 200, patched.text
    assert patched.json()["status"] == "resolved"

    assert (await client.get("/feedback", params={"status": "resolved"})).json()["total"] == 1
    assert (await client.get("/feedback", params={"status": "open"})).json()["total"] == 0

    stats = (await client.get("/feedback/stats")).json()
    assert stats["total"] == 1
