"""The last complete `GET /github/repos` listing, kept so the page need not wait on GitHub.

Asking GitHub costs one round-trip for the installation list plus one per
installation, which is seconds, not milliseconds. This cache holds the last
listing GitHub confirmed as ``complete`` (every installation answered) and
when it was fetched. The route decides what that age means; this module only
stores it.

Only complete listings are stored, so a cached listing never claims more than
GitHub once confirmed. Production keeps it in Redis, shared across replicas and
surviving a restart; a lost or unreachable Redis costs speed, never
correctness, because a miss means asking GitHub live as before (ADR-060: no
in-memory store outside test/offline).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Protocol

from pydantic import BaseModel, ConfigDict, ValidationError

from syn_adapters.in_memory import InMemoryAdapter
from syn_api.types import GitHubRepoResponse  # noqa: TC001  # Pydantic resolves it at runtime

if TYPE_CHECKING:
    from redis.asyncio import Redis as AsyncRedis

logger = logging.getLogger(__name__)

# How long a listing may be served as complete. A repo added to an installation
# reaches a complete listing within this, or at once via the
# installation_repositories webhook, which invalidates the cache.
FRESH_FOR = timedelta(seconds=60)

# How long a listing is kept at all. Older than FRESH_FOR it is only served as
# partial while a refresh runs; past this it is gone and the next request asks
# GitHub live.
_RETAINED_FOR = timedelta(hours=1)

_KEY = "syn:github:repo_listing"


class CachedRepoListing(BaseModel):
    """A listing GitHub confirmed complete, with the time it was asked."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    repos: list[GitHubRepoResponse]
    fetched_at: datetime

    def is_fresh(self, now: datetime | None = None) -> bool:
        """Whether this listing may still be served as complete."""
        return (now or datetime.now(UTC)) - self.fetched_at < FRESH_FOR


class RepoListingCache(Protocol):
    """Where the last complete listing is kept."""

    async def get(self) -> CachedRepoListing | None: ...
    async def put(self, listing: CachedRepoListing) -> None: ...
    async def invalidate(self) -> None: ...


class RedisRepoListingCache:
    """Redis-backed listing cache. Fails open: a Redis error is a miss."""

    def __init__(self, redis: AsyncRedis) -> None:
        self._redis = redis

    async def get(self) -> CachedRepoListing | None:
        try:
            raw: str | None = await self._redis.get(_KEY)
        except Exception:
            logger.warning("GitHub repo listing cache unreadable; asking GitHub", exc_info=True)
            return None
        if raw is None:
            return None
        try:
            return CachedRepoListing.model_validate_json(raw)
        except ValidationError:
            logger.warning("Discarding unreadable GitHub repo listing cache entry")
            return None

    async def put(self, listing: CachedRepoListing) -> None:
        try:
            await self._redis.set(
                _KEY, listing.model_dump_json(), ex=int(_RETAINED_FOR.total_seconds())
            )
        except Exception:
            logger.warning("Could not store GitHub repo listing cache", exc_info=True)

    async def invalidate(self) -> None:
        try:
            await self._redis.delete(_KEY)
        except Exception:
            # The entry then lives until FRESH_FOR runs out: the TTL bound holds.
            logger.warning("Could not invalidate GitHub repo listing cache", exc_info=True)


class InMemoryRepoListingCache(InMemoryAdapter):
    """Test/offline listing cache (ADR-060: refuses to construct elsewhere)."""

    def __init__(self) -> None:
        super().__init__()
        self._listing: CachedRepoListing | None = None

    async def get(self) -> CachedRepoListing | None:
        return self._listing

    async def put(self, listing: CachedRepoListing) -> None:
        self._listing = listing

    async def invalidate(self) -> None:
        self._listing = None


_cache_singleton: RepoListingCache | None = None


def get_repo_listing_cache() -> RepoListingCache:
    """Return the process-wide listing cache: in memory under test, else Redis."""
    global _cache_singleton
    if _cache_singleton is None:
        from syn_shared.settings import get_settings

        settings = get_settings()
        if settings.uses_in_memory_stores:
            _cache_singleton = InMemoryRepoListingCache()
        else:
            from syn_adapters.redis_client import resilient_redis_client

            _cache_singleton = RedisRepoListingCache(resilient_redis_client(settings.redis_url))
    return _cache_singleton


def reset_repo_listing_cache() -> None:
    """Forget the process-wide cache (tests)."""
    global _cache_singleton
    _cache_singleton = None
