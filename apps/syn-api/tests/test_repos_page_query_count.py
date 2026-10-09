"""The repos page's requests cost the same number of reads however many repos exist.

Owner feedback 0afb5d92: the page took seconds to load. It waits on /repos,
/systems and /github/repos together. Each test drives the real service function
the route calls and counts what it asks of its store or of GitHub, at two sizes:
a per-repo read would make the counts differ.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from syn_api.routes import github as github_routes
from syn_api.routes.github import list_accessible_repos
from syn_api.routes.repos import list_repos
from syn_api.routes.systems import list_systems
from syn_api.services.github_repo_listing_cache import (
    FRESH_FOR,
    CachedRepoListing,
    get_repo_listing_cache,
)
from syn_api.types import GitHubRepoLookup, GitHubRepoResponse, Ok
from syn_domain.contexts.organization.slices.list_repos.projection import RepoProjection
from syn_domain.contexts.organization.slices.list_systems.projection import SystemProjection

pytestmark = pytest.mark.unit

SIZES = (3, 300)


@dataclass
class _CountingStore:
    """A projection store that counts every read."""

    tables: dict[str, dict[str, dict]] = field(default_factory=dict)
    reads: int = 0

    async def get(self, projection: str, key: str) -> dict | None:
        self.reads += 1
        record = self.tables.get(projection, {}).get(key)
        return json.loads(json.dumps(record)) if record is not None else None

    async def get_all(self, projection: str) -> list[dict]:
        self.reads += 1
        return [json.loads(json.dumps(r)) for r in self.tables.get(projection, {}).values()]

    async def save(self, projection: str, key: str, data: dict) -> None:
        self.tables.setdefault(projection, {})[key] = json.loads(json.dumps(data, default=str))


async def _organization(repos: int) -> _CountingStore:
    store = _CountingStore()
    systems = SystemProjection(store)  # type: ignore[arg-type]  # duck-typed store
    registry = RepoProjection(store)  # type: ignore[arg-type]
    for s in range(5):
        await systems.on_system_created({"system_id": f"sys-{s}", "name": f"System {s}"})
    for n in range(repos):
        event = {"repo_id": f"repo-{n}", "system_id": f"sys-{n % 5}", "full_name": f"a/r{n}"}
        await registry.on_repo_registered(event)
        await systems.on_repo_registered_increment(event)
    store.reads = 0
    return store


@pytest.fixture(autouse=True)
def _connected() -> object:
    with (
        patch("syn_api.routes.repos.ensure_connected", new_callable=AsyncMock),
        patch("syn_api.routes.systems.ensure_connected", new_callable=AsyncMock),
        patch("syn_api.routes.github.ensure_connected", new_callable=AsyncMock),
    ):
        yield


async def _reads_for_repos(repos: int) -> int:
    store = await _organization(repos)
    with patch(
        "syn_domain.contexts.organization.get_repo_projection",
        return_value=RepoProjection(store),  # type: ignore[arg-type]
    ):
        result = await list_repos()
    assert isinstance(result, Ok)
    assert len(result.value) == repos
    return store.reads


async def _reads_for_systems(repos: int) -> int:
    store = await _organization(repos)
    with patch(
        "syn_domain.contexts.organization.get_system_projection",
        return_value=SystemProjection(store),  # type: ignore[arg-type]
    ):
        result = await list_systems()
    assert isinstance(result, Ok)
    assert sum(s.repo_count for s in result.value) == repos
    return store.reads


async def test_listing_repos_reads_the_store_once_however_many_repos() -> None:
    assert [await _reads_for_repos(n) for n in SIZES] == [1, 1]


async def test_listing_systems_reads_the_store_once_however_many_repos() -> None:
    assert [await _reads_for_systems(n) for n in SIZES] == [1, 1]


@dataclass
class _GitHub:
    calls: list[str] = field(default_factory=list)

    async def list_installations(self) -> list[dict]:
        self.calls.append("installations")
        return []

    async def list_accessible_repos(self, installation_id: str | None = None) -> list[dict]:
        self.calls.append(f"repos:{installation_id}")
        return []


async def _github_calls_on_request(repos: int, age: timedelta) -> tuple[int, GitHubRepoLookup]:
    """GitHub calls one /github/repos request waits on, with a listing of ``repos`` aged ``age``."""
    cache = get_repo_listing_cache()
    generation = await cache.generation()
    assert generation is not None
    listing = [
        GitHubRepoResponse(
            github_id=n,
            name=f"r{n}",
            full_name=f"a/r{n}",
            private=False,
            default_branch="main",
            owner="a",
            installation_id="inst-1",
        )
        for n in range(repos)
    ]
    await cache.put(
        CachedRepoListing(repos=listing, fetched_at=datetime.now(UTC) - age, generation=generation)
    )
    github = _GitHub()
    with (
        patch("syn_adapters.github.client.get_github_client", return_value=github),
        # The background refresh is started, not awaited: it is not on the request.
        patch.object(
            github_routes, "_revalidate_in_background", new_callable=AsyncMock
        ) as refresh,
    ):
        result = await list_accessible_repos()
    assert isinstance(result, Ok)
    assert result.value.total == repos
    refresh.assert_called_once()
    return len(github.calls), result.value.lookup


@pytest.mark.parametrize("age", [FRESH_FOR + timedelta(seconds=1), timedelta(hours=20)])
async def test_an_expired_app_listing_is_served_without_asking_github(age: timedelta) -> None:
    """The /repos page opened after a while away: served at once, labelled partial."""
    answers = [await _github_calls_on_request(n, age) for n in SIZES]
    assert answers == [(0, GitHubRepoLookup.PARTIAL)] * len(SIZES)
