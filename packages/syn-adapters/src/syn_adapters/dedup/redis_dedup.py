"""Redis-backed dedup adapter using SETNX + TTL."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from redis.asyncio import Redis as AsyncRedis

_DEDUP_TTL_SECONDS = 86400  # 24 hours
_KEY_PREFIX = "syn:dedup:"


class RedisDedupAdapter:
    """Redis-backed dedup using SETNX + TTL.

    Implements :class:`~syn_domain.contexts.github.slices.event_pipeline.dedup_port.DedupPort`.

    Uses ``SET key <token> NX EX ttl`` for atomic check-and-mark, where
    ``<token>`` is unique to the call. The client retries a command whose
    reply was lost (#1756), and the retry of an applied ``SET NX`` finds the
    key its own first attempt wrote. The token tells the two apart: a key
    holding *this call's* token was first seen by this call, a key holding
    anything else was seen before it.
    """

    def __init__(self, redis: AsyncRedis, ttl_seconds: int = _DEDUP_TTL_SECONDS) -> None:
        self._redis = redis
        self._ttl = ttl_seconds

    async def is_duplicate(self, dedup_key: str) -> bool:
        """Return ``True`` if this key was already seen (duplicate)."""
        key = f"{_KEY_PREFIX}{dedup_key}"
        token = uuid.uuid4().hex
        # SET NX returns True if the key was SET (new), None if it already existed.
        was_set: bool | None = await self._redis.set(key, token, nx=True, ex=self._ttl)
        if was_set:
            return False
        holder: str | bytes | None = await self._redis.get(key)
        return holder not in (token, token.encode())

    async def mark_seen(self, dedup_key: str) -> None:
        """Explicitly mark a key as seen."""
        key = f"{_KEY_PREFIX}{dedup_key}"
        await self._redis.set(key, "1", ex=self._ttl)
