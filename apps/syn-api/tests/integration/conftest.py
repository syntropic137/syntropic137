"""Fixtures shared by the E2 latency gate and its parity test.

One seeded TimescaleDB per test, built by the gate module's ``seed``: see
test_list_detail_latency_budget.py for what it holds and why.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from urllib.parse import urlsplit, urlunsplit

import asyncpg
import httpx
import pytest

from . import test_list_detail_latency_budget as gate

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


def _with_database(url: str, name: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, f"/{name}", "", ""))


@pytest.fixture
async def e2_database(test_infrastructure) -> AsyncIterator[str]:
    """An empty database of its own, dropped afterwards."""
    admin_url = test_infrastructure.timescaledb_url
    name = f"latency_gate_e2_{uuid.uuid4().hex[:12]}"
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


@pytest.fixture
async def e2_seeded_client(
    e2_database: str, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[httpx.AsyncClient]:
    """The real app, wired to a seeded TimescaleDB for both stores it reads."""
    from syn_adapters import projection_stores
    from syn_adapters.events import AgentEventStore, store_helpers
    from syn_adapters.projection_stores import PostgresProjectionStore
    from syn_adapters.projections.manager import reset_projection_manager
    from syn_api.main import create_app
    from syn_api.services import github_repo_listing_cache as repo_listing_cache
    from syn_domain.contexts.github.slices.get_installation import (
        projection as get_installation,
    )
    from syn_domain.contexts.organization.slices.list_repos import projection as list_repos
    from syn_domain.contexts.organization.slices.list_systems import projection as list_systems

    store = AgentEventStore(e2_database)
    await store.initialize()
    pool = store.pool
    assert pool is not None
    monkeypatch.setattr(store_helpers, "_event_store", store)
    monkeypatch.setattr(projection_stores, "_store_instance", PostgresProjectionStore(pool))
    reset_projection_manager()
    gate.use_timescale_timeline(pool)

    await gate.seed(pool, datetime.now(UTC).replace(microsecond=0))
    # GitHub answers slowly; the repos page must not be waiting on it.
    monkeypatch.setattr("syn_adapters.github.client.get_github_client", gate.SlowGitHub)
    monkeypatch.setattr(repo_listing_cache, "_cache_singleton", None)
    for projection in (list_repos, list_systems, get_installation):
        # Module singletons: built on first use, so on the store patched above.
        monkeypatch.setattr(projection, "_projection", None)
    await gate.seed_expired_app_listing()

    try:
        transport = httpx.ASGITransport(app=create_app())
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            yield client
    finally:
        reset_projection_manager()
        await store.close()
