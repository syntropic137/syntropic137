"""One contract, two PendingSHAStore adapters (#602, ADR-060).

The same assertions run against InMemoryPendingSHAStore (unit) and the
PostgresPendingSHAStore production wires instead (integration, against the
test stack's TimescaleDB on 15432, or ``TEST_DATABASE_URL``). The keyspace is
``(repository, sha)`` in both: a fake keyed by sha alone would let one repo's
completed checks stop another repo's polling, and only production would show it.

Every test uses its own repository name, so the Postgres leg can share a
table with other runs. The integration leg skips, never passes, when the
database does not answer.
"""

from __future__ import annotations

import os
import socket
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from urllib.parse import urlparse
from uuid import uuid4

import pytest

from syn_adapters.github.pending_sha_store import InMemoryPendingSHAStore
from syn_adapters.github.postgres_pending_sha_store import PostgresPendingSHAStore
from syn_domain.contexts.github import PendingSHA
from syn_shared.testing import ENV_TEST_DATABASE_URL, get_test_timescaledb_url

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

PendingSHAStore = InMemoryPendingSHAStore | PostgresPendingSHAStore


def _require(url: str) -> None:
    parsed = urlparse(url)
    try:
        with socket.create_connection((parsed.hostname or "", parsed.port or 0), timeout=1):
            return
    except OSError:
        pytest.skip(f"no backend at {parsed.hostname}:{parsed.port}")


@pytest.fixture(
    params=[
        pytest.param("memory", marks=pytest.mark.unit),
        pytest.param("postgres", marks=pytest.mark.integration),
    ]
)
async def store(request: pytest.FixtureRequest) -> AsyncIterator[PendingSHAStore]:
    if request.param == "memory":
        yield InMemoryPendingSHAStore()
    else:
        import asyncpg

        url = os.getenv(ENV_TEST_DATABASE_URL, get_test_timescaledb_url())
        _require(url)
        pool = await asyncpg.create_pool(url, min_size=1, max_size=2)
        yield PostgresPendingSHAStore(pool)
        await pool.close()


def _repo() -> str:
    return f"contract/{uuid4().hex}"


def _pending(
    repository: str, sha: str, *, pr_number: int = 1, registered_at: datetime | None = None
) -> PendingSHA:
    return PendingSHA(
        repository=repository,
        sha=sha,
        pr_number=pr_number,
        branch="feature",
        installation_id="inst-1",
        registered_at=registered_at or datetime.now(UTC),
    )


async def _mine(store: PendingSHAStore, repository: str) -> list[PendingSHA]:
    return [p for p in await store.list_pending() if p.repository == repository]


async def test_registered_sha_is_listed_with_its_fields(store: PendingSHAStore) -> None:
    repo = _repo()
    await store.register(_pending(repo, "abc", pr_number=42))
    [listed] = await _mine(store, repo)
    assert (listed.sha, listed.pr_number, listed.branch, listed.installation_id) == (
        "abc",
        42,
        "feature",
        "inst-1",
    )


async def test_registering_the_same_sha_twice_keeps_the_first(store: PendingSHAStore) -> None:
    repo = _repo()
    await store.register(_pending(repo, "abc", pr_number=1))
    await store.register(_pending(repo, "abc", pr_number=2))
    assert [p.pr_number for p in await _mine(store, repo)] == [1]


async def test_the_same_sha_in_two_repositories_is_two_entries(store: PendingSHAStore) -> None:
    first, second = _repo(), _repo()
    await store.register(_pending(first, "abc"))
    await store.register(_pending(second, "abc"))
    await store.remove(first, "abc")
    assert await _mine(store, first) == []
    assert [p.sha for p in await _mine(store, second)] == ["abc"]


async def test_cleanup_removes_only_entries_older_than_max_age(store: PendingSHAStore) -> None:
    repo = _repo()
    await store.register(_pending(repo, "old", registered_at=datetime.now(UTC) - timedelta(days=2)))
    await store.register(_pending(repo, "new"))
    removed = await store.cleanup_stale(timedelta(days=1))
    assert removed >= 1
    assert [p.sha for p in await _mine(store, repo)] == ["new"]
