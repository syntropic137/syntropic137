"""`GET /github/repos` serves a cached complete listing instead of waiting on GitHub.

Each test drives the real service function (or the real webhook handler) with
a GitHub stand-in that counts its calls, and reads the cache through the same
getter the route uses.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

from syn_api.routes import github as github_routes
from syn_api.routes.github import list_accessible_repos
from syn_api.routes.webhooks.handlers import _handle_installation_event
from syn_api.services.github_repo_listing_cache import (
    FRESH_FOR,
    CachedRepoListing,
    RedisRepoListingCache,
    get_repo_listing_cache,
)
from syn_api.types import GitHubRepoListResponse, GitHubRepoLookup, GitHubRepoResponse, Ok

pytestmark = pytest.mark.unit

_PROJECTION = (
    "syn_domain.contexts.github.slices.get_installation.projection.get_installation_projection"
)


@dataclass
class _GitHub:
    """A GitHub App that reaches ``repos`` per installation, or fails while ``down``."""

    repos: dict[str, list[str]]
    down: bool = False
    calls: list[str] = field(default_factory=list)

    async def list_installations(self) -> list[dict]:
        self.calls.append("installations")
        if self.down:
            raise RuntimeError("GitHub 502")
        return [{"id": inst} for inst in self.repos]

    async def list_accessible_repos(self, installation_id: str | None = None) -> list[dict]:
        self.calls.append(f"repos:{installation_id}")
        if self.down:
            raise RuntimeError("GitHub 502")
        return [
            {
                "id": abs(hash(name)) % 10**9,
                "name": name.split("/")[1],
                "full_name": name,
                "private": name.endswith("-private"),
                "default_branch": "main",
            }
            for name in self.repos[str(installation_id)]
        ]


def _projection(installation_ids: list[str]) -> MagicMock:
    def _inst(installation_id: str) -> MagicMock:
        inst = MagicMock()
        inst.installation_id = installation_id
        return inst

    projection = MagicMock()
    projection.upsert_from_github_api = AsyncMock(side_effect=lambda raw: _inst(str(raw["id"])))
    projection.get_all_active = AsyncMock(return_value=[_inst(i) for i in installation_ids])
    projection.update_repositories = AsyncMock()
    return projection


@pytest.fixture
def github() -> Iterator[_GitHub]:
    gh = _GitHub(repos={"inst-1": ["acme/payments"], "inst-2": ["acme/billing"]})
    with (
        patch("syn_api.routes.github.ensure_connected", new_callable=AsyncMock),
        patch("syn_adapters.github.client.get_github_client", return_value=gh),
        patch(_PROJECTION, return_value=_projection(list(gh.repos))),
        patch("syn_domain.contexts.github.get_installation_projection", return_value=_projection([])),
        patch.object(github_routes, "_revalidation", None),
    ):
        yield gh


async def _listing(include_private: bool = True) -> GitHubRepoListResponse:
    result = await list_accessible_repos(include_private=include_private)
    assert isinstance(result, Ok)
    return result.value


def _names(listing: GitHubRepoListResponse) -> list[str]:
    return sorted(r.full_name for r in listing.repos)


async def _age_cache(by: timedelta) -> None:
    cache = get_repo_listing_cache()
    cached = await cache.get()
    assert cached is not None
    await cache.put(cached.model_copy(update={"fetched_at": cached.fetched_at - by}))


async def _finish_revalidation() -> None:
    task = github_routes._revalidation
    assert task is not None, "no background refresh was started"
    await asyncio.wait_for(task, timeout=5)


async def test_a_fresh_cache_answers_without_asking_github(github: _GitHub) -> None:
    first = await _listing()
    asked = len(github.calls)
    second = await _listing()

    assert asked == 3  # the installation list, then each installation
    assert len(github.calls) == asked
    assert (_names(second), second.lookup) == (_names(first), GitHubRepoLookup.COMPLETE)


async def test_an_expired_cache_is_served_partial_and_refreshed(github: _GitHub) -> None:
    await _listing()
    github.repos["inst-1"].append("acme/new")
    await _age_cache(FRESH_FOR + timedelta(seconds=1))

    stale = await _listing()
    assert stale.lookup == GitHubRepoLookup.PARTIAL
    assert "acme/new" not in _names(stale)

    await _finish_revalidation()
    refreshed = await _listing()
    assert refreshed.lookup == GitHubRepoLookup.COMPLETE
    assert "acme/new" in _names(refreshed)


async def test_an_installation_webhook_drops_the_cache(github: _GitHub) -> None:
    await _listing()
    github.repos["inst-2"].append("acme/new")

    await _handle_installation_event(
        "installation_repositories",
        "added",
        {"installation": {"id": "inst-2"}, "repositories_added": [{"full_name": "acme/new"}]},
    )
    after = await _listing()

    assert (after.lookup, "acme/new" in _names(after)) == (GitHubRepoLookup.COMPLETE, True)


@pytest.mark.parametrize("action", ["created", "deleted", "suspend", "unsuspend"])
async def test_every_installation_action_drops_the_cache(github: _GitHub, action: str) -> None:
    await _listing()
    with patch("syn_api.routes.webhooks.handlers._apply_installation_created", AsyncMock()):
        await _handle_installation_event("installation", action, {"installation": {"id": 1}})
    assert await get_repo_listing_cache().get() is None


async def test_github_down_with_a_warm_cache_serves_it_stale_and_keeps_it(
    github: _GitHub,
) -> None:
    before = await _listing()
    await _age_cache(FRESH_FOR + timedelta(seconds=1))
    github.down = True

    stale = await _listing()
    await _finish_revalidation()

    assert (_names(stale), stale.lookup) == (_names(before), GitHubRepoLookup.PARTIAL)
    kept = await get_repo_listing_cache().get()
    assert kept is not None
    assert sorted(r.full_name for r in kept.repos) == _names(before)


async def test_github_down_with_a_cold_cache_is_unavailable_as_before(github: _GitHub) -> None:
    github.down = True
    listing = await _listing()
    assert (listing.repos, listing.lookup) == ([], GitHubRepoLookup.UNAVAILABLE)
    assert await get_repo_listing_cache().get() is None


async def test_a_partial_answer_is_not_cached(github: _GitHub) -> None:
    original = github.list_accessible_repos

    async def inst_2_fails(installation_id: str | None = None) -> list[dict]:
        if installation_id == "inst-2":
            raise RuntimeError("GitHub 502")
        return await original(installation_id)

    with patch.object(github, "list_accessible_repos", inst_2_fails):
        partial = await _listing()
    assert partial.lookup == GitHubRepoLookup.PARTIAL
    assert await get_repo_listing_cache().get() is None


async def test_private_repos_are_filtered_from_the_cached_listing(github: _GitHub) -> None:
    github.repos["inst-1"].append("acme/secret-private")
    await _listing()
    public = await _listing(include_private=False)
    assert "acme/secret-private" not in _names(public)
    assert "acme/payments" in _names(public)


class _Redis:
    def __init__(self, *, broken: bool = False) -> None:
        self.values: dict[str, str] = {}
        self.ttls: dict[str, int] = {}
        self.broken = broken

    async def get(self, key: str) -> str | None:
        if self.broken:
            raise RedisConnectionError("down")
        return self.values.get(key)

    async def set(self, key: str, value: str, ex: int) -> None:
        if self.broken:
            raise RedisConnectionError("down")
        self.values[key], self.ttls[key] = value, ex

    async def delete(self, key: str) -> None:
        if self.broken:
            raise RedisConnectionError("down")
        self.values.pop(key, None)


def _cached() -> CachedRepoListing:
    repo = GitHubRepoResponse(
        github_id=7,
        name="payments",
        full_name="acme/payments",
        private=True,
        default_branch="main",
        owner="acme",
        installation_id="inst-1",
    )
    return CachedRepoListing(repos=[repo], fetched_at=datetime.now(UTC))


async def test_redis_cache_round_trips_and_expires_the_key() -> None:
    redis = _Redis()
    cache = RedisRepoListingCache(redis)  # type: ignore[arg-type]  # stand-in for redis.asyncio.Redis

    listing = _cached()
    await cache.put(listing)
    assert await cache.get() == listing
    assert list(redis.ttls.values()) == [3600]
    await cache.invalidate()
    assert await cache.get() is None


async def test_unreachable_redis_is_a_miss_not_an_error() -> None:
    cache = RedisRepoListingCache(_Redis(broken=True))  # type: ignore[arg-type]  # stand-in
    await cache.put(_cached())
    await cache.invalidate()
    assert await cache.get() is None
