"""`GET /github/repos` serves a cached complete listing instead of waiting on GitHub.

Each test drives the real service function (or the real webhook handler) with
a GitHub stand-in that counts its calls, and reads the cache through the same
getter the route uses.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

from syn_api.routes import github as github_routes
from syn_api.routes.github import list_accessible_repos
from syn_api.routes.webhooks.handlers import _handle_installation_event
from syn_api.services import github_repo_listing_cache as listing_cache_module
from syn_api.services.github_repo_listing_cache import (
    FRESH_FOR,
    INVALIDATE,
    PUT_IF_CURRENT,
    REFRESH_AFTER,
    CachedRepoListing,
    InMemoryRepoListingCache,
    RedisRepoListingCache,
    get_repo_listing_cache,
)
from syn_api.types import GitHubRepoListResponse, GitHubRepoLookup, GitHubRepoResponse, Ok

if TYPE_CHECKING:
    from collections.abc import Iterator

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
        patch(
            "syn_domain.contexts.github.get_installation_projection", return_value=_projection([])
        ),
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


async def test_the_first_request_after_expiry_asks_github_and_has_the_new_repo(
    github: _GitHub,
) -> None:
    """No webhook: a repo added is in the first listing served once FRESH_FOR runs out."""
    await _listing()
    github.repos["inst-1"].append("acme/new")
    await _age_cache(FRESH_FOR + timedelta(seconds=1))
    asked = len(github.calls)

    first = await _listing()

    assert len(github.calls) > asked
    assert (first.lookup, "acme/new" in _names(first)) == (GitHubRepoLookup.COMPLETE, True)


async def test_a_listing_past_refresh_after_is_served_and_refreshed_behind(
    github: _GitHub,
) -> None:
    await _listing()
    github.repos["inst-1"].append("acme/new")
    await _age_cache(REFRESH_AFTER + timedelta(seconds=1))

    served = await _listing()
    assert (served.lookup, "acme/new" in _names(served)) == (GitHubRepoLookup.COMPLETE, False)

    await _finish_revalidation()
    asked = len(github.calls)
    refreshed = await _listing()
    assert len(github.calls) == asked  # answered from the refreshed cache
    assert (refreshed.lookup, "acme/new" in _names(refreshed)) == (GitHubRepoLookup.COMPLETE, True)


async def test_a_webhook_during_a_refresh_outranks_the_refresh(github: _GitHub) -> None:
    """A refresh that read GitHub before the webhook must not be served after it."""
    await _listing()
    await _age_cache(REFRESH_AFTER + timedelta(seconds=1))
    original = github.list_accessible_repos
    read_old_answer, release = asyncio.Event(), asyncio.Event()

    async def pauses_after_reading(installation_id: str | None = None) -> list[dict]:
        answer = await original(installation_id)
        if installation_id == "inst-2" and not release.is_set():
            read_old_answer.set()
            await release.wait()
        return answer

    with patch.object(github, "list_accessible_repos", pauses_after_reading):
        await _listing()  # starts the background refresh
        await asyncio.wait_for(read_old_answer.wait(), timeout=5)

        github.repos["inst-2"].append("acme/new")
        await _handle_installation_event(
            "installation_repositories",
            "added",
            {"installation": {"id": "inst-2"}, "repositories_added": [{"full_name": "acme/new"}]},
        )
        release.set()
        await _finish_revalidation()

        after = await _listing()

    assert (after.lookup, "acme/new" in _names(after)) == (GitHubRepoLookup.COMPLETE, True)


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
    """Redis as the cache uses it. Each command, scripts included, runs whole.

    ``after_generation_bump``, when set, is awaited once a command has bumped
    the generation, which is the only point another caller can get in.
    """

    def __init__(self, *, broken: bool = False) -> None:
        self.values: dict[str, str] = {}
        self.ttls: dict[str, int] = {}
        self.broken = broken
        self.after_generation_bump: asyncio.Event | None = None

    async def _bumped(self) -> None:
        if self.after_generation_bump is not None:
            await self.after_generation_bump.wait()

    async def eval(self, script: str, numkeys: int, *keys_and_args: str) -> int:
        if self.broken:
            raise RedisConnectionError("down")
        (listing_key, generation_key), args = keys_and_args[:numkeys], keys_and_args[numkeys:]
        if script == PUT_IF_CURRENT:
            value, generation, ttl = args
            if int(self.values.get(generation_key, "0")) != int(generation):
                return 0
            self.values[listing_key], self.ttls[listing_key] = value, int(ttl)
            return 1
        if script == INVALIDATE:
            self.values[generation_key] = str(int(self.values.get(generation_key, "0")) + 1)
            self.values.pop(listing_key, None)
            await self._bumped()
            return 1
        raise AssertionError(f"unexpected script: {script!r}")

    async def get(self, key: str) -> str | None:
        if self.broken:
            raise RedisConnectionError("down")
        return self.values.get(key)

    async def mget(self, *keys: str) -> list[str | None]:
        if self.broken:
            raise RedisConnectionError("down")
        return [self.values.get(k) for k in keys]

    async def incr(self, key: str) -> int:
        if self.broken:
            raise RedisConnectionError("down")
        self.values[key] = str(int(self.values.get(key, "0")) + 1)
        await self._bumped()
        return int(self.values[key])

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
    return CachedRepoListing(repos=[repo], fetched_at=datetime.now(UTC), generation=0)


async def test_redis_cache_round_trips_and_expires_the_key() -> None:
    redis = _Redis()
    cache = RedisRepoListingCache(redis)  # type: ignore[arg-type]  # stand-in for redis.asyncio.Redis

    listing = _cached()
    await cache.put(listing)
    assert await cache.get() == listing
    assert list(redis.ttls.values()) == [3600]
    await cache.invalidate()
    assert await cache.get() is None


async def test_redis_cache_ignores_a_listing_put_from_before_an_invalidation() -> None:
    cache = RedisRepoListingCache(_Redis())  # type: ignore[arg-type]  # stand-in for redis.asyncio.Redis

    read_before = await cache.generation()
    await cache.invalidate()
    await cache.put(_cached().model_copy(update={"generation": read_before}))
    assert await cache.get() is None

    current = await cache.generation()
    assert current is not None and current != read_before
    fresh = _cached().model_copy(update={"generation": current})
    await cache.put(fresh)
    assert await cache.get() == fresh


def _generation(listing: CachedRepoListing, generation: int | None) -> CachedRepoListing:
    assert generation is not None
    return listing.model_copy(update={"generation": generation})


async def test_redis_cache_keeps_a_newer_listing_over_a_late_older_refresh() -> None:
    """Refresh A reads, a webhook invalidates, refresh B stores, then A finishes."""
    cache = RedisRepoListingCache(_Redis())  # type: ignore[arg-type]  # stand-in for redis.asyncio.Redis

    read_by_a = await cache.generation()
    await cache.invalidate()
    newer = _generation(_cached(), await cache.generation())
    await cache.put(newer)
    await cache.put(_generation(_cached(), read_by_a))

    assert await cache.get() == newer


async def test_redis_cache_keeps_a_listing_stored_while_an_invalidation_is_in_flight() -> None:
    """A listing stored under the new generation survives the invalidation that made it."""
    redis = _Redis()
    cache = RedisRepoListingCache(redis)  # type: ignore[arg-type]  # stand-in for redis.asyncio.Redis
    redis.after_generation_bump = release = asyncio.Event()

    invalidating = asyncio.create_task(cache.invalidate())
    while redis.values.get("syn:github:repo_listing:generation") is None:
        await asyncio.sleep(0)
    newer = _generation(_cached(), await cache.generation())
    await cache.put(newer)
    release.set()
    await asyncio.wait_for(invalidating, timeout=5)

    assert await cache.get() == newer


@pytest.mark.parametrize("backend", ["redis", "in_memory"])
async def test_a_late_refresh_does_not_cost_the_newer_listing_its_stale_fallback(
    github: _GitHub, backend: str
) -> None:
    """Refresh A reads GitHub, a webhook lands, refresh B stores, A finishes, GitHub goes down.

    The listing B stored is the current one, so it must still be served as
    stale ``partial`` rather than the page falling to ``unavailable``.
    """
    listing_cache_module._cache_singleton = (
        RedisRepoListingCache(_Redis())  # type: ignore[arg-type]  # stand-in for redis.asyncio.Redis
        if backend == "redis"
        else InMemoryRepoListingCache()
    )
    await _listing()
    await _age_cache(REFRESH_AFTER + timedelta(seconds=1))
    original = github.list_accessible_repos
    a_read_old_answer, release_a = asyncio.Event(), asyncio.Event()

    async def a_pauses_after_reading(installation_id: str | None = None) -> list[dict]:
        answer = await original(installation_id)
        if installation_id == "inst-2" and not a_read_old_answer.is_set():
            a_read_old_answer.set()
            await release_a.wait()
        return answer

    with patch.object(github, "list_accessible_repos", a_pauses_after_reading):
        await _listing()  # serves the cache and starts refresh A behind it
        await asyncio.wait_for(a_read_old_answer.wait(), timeout=5)

        github.repos["inst-2"].append("acme/new")
        await _handle_installation_event(
            "installation_repositories",
            "added",
            {"installation": {"id": "inst-2"}, "repositories_added": [{"full_name": "acme/new"}]},
        )
        b = await _listing()  # the cache is gone, so B asks GitHub and stores its answer
        assert (b.lookup, "acme/new" in _names(b)) == (GitHubRepoLookup.COMPLETE, True)

        release_a.set()
        await _finish_revalidation()

    await _age_cache(FRESH_FOR + timedelta(seconds=1))
    github.down = True
    stale = await _listing()

    assert (stale.lookup, "acme/new" in _names(stale)) == (GitHubRepoLookup.PARTIAL, True)


async def test_unreachable_redis_is_a_miss_not_an_error() -> None:
    cache = RedisRepoListingCache(_Redis(broken=True))  # type: ignore[arg-type]  # stand-in
    assert await cache.generation() is None
    await cache.put(_cached())
    await cache.invalidate()
    assert await cache.get() is None
