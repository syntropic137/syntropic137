"""Redis-backed dedup adapter using SETNX + TTL."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from redis.asyncio import Redis as AsyncRedis

_DEDUP_TTL_SECONDS = 86400  # 24 hours
_KEY_PREFIX = "syn:dedup:"


class RedisDedupAdapter:
    """Redis-backed dedup using SETNX + TTL.

    Implements :class:`~syn_domain.contexts.github.slices.event_pipeline.dedup_port.DedupPort`.

    Uses ``SET key 1 NX EX ttl`` for atomic check-and-mark: if the key
    already exists the SET is a no-op and ``is_duplicate`` returns ``True``.
    """

    def __init__(self, redis: AsyncRedis, ttl_seconds: int = _DEDUP_TTL_SECONDS) -> None:
        self._redis = redis
        self._ttl = ttl_seconds

    async def is_duplicate(self, dedup_key: str) -> bool:
        """Return ``True`` if this key was already seen (duplicate)."""
        key = f"{_KEY_PREFIX}{dedup_key}"
        # SET NX returns True if the key was SET (new), None if it already existed.
        was_set: bool | None = await self._redis.set(key, "1", nx=True, ex=self._ttl)
        return not was_set

    async def mark_seen(self, dedup_key: str) -> None:
        """Explicitly mark a key as seen."""
        key = f"{_KEY_PREFIX}{dedup_key}"
        await self._redis.set(key, "1", ex=self._ttl)
