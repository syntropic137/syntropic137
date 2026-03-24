"""Redis-backed token store implementation.

Extracted from token_stores.py to reduce module complexity.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from syn_tokens.models import ScopedToken
from syn_tokens.token_stores import REDIS_EXECUTION_TOKENS_PREFIX, REDIS_TOKEN_PREFIX, TokenStore

if TYPE_CHECKING:
    from redis.asyncio import Redis

logger = logging.getLogger(__name__)


class RedisTokenStore(TokenStore):
    """Redis-backed token store with automatic TTL expiry."""

    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def store(self, token: ScopedToken) -> None:
        """Store a token with TTL."""
        key = f"{REDIS_TOKEN_PREFIX}{token.token_id}"
        exec_key = f"{REDIS_EXECUTION_TOKENS_PREFIX}{token.execution_id}"

        await self._redis.setex(
            key,
            token.ttl_seconds,
            json.dumps(token.to_dict()),
        )

        await self._redis.sadd(exec_key, token.token_id)  # type: ignore[misc]
        await self._redis.expire(exec_key, token.ttl_seconds + 60)

        logger.debug(
            "Token stored (token_id=%s, execution_id=%s, ttl=%ds)",
            token.token_id,
            token.execution_id,
            token.ttl_seconds,
        )

    async def get(self, token_id: str) -> ScopedToken | None:
        """Get a token by ID."""
        key = f"{REDIS_TOKEN_PREFIX}{token_id}"
        data = await self._redis.get(key)
        if data is None:
            return None
        return ScopedToken.from_dict(json.loads(data))

    async def delete(self, token_id: str) -> bool:
        """Delete a token."""
        key = f"{REDIS_TOKEN_PREFIX}{token_id}"
        deleted = await self._redis.delete(key)
        return deleted > 0

    async def get_tokens_for_execution(self, execution_id: str) -> list[str]:
        """Get all token IDs for an execution."""
        exec_key = f"{REDIS_EXECUTION_TOKENS_PREFIX}{execution_id}"
        members = await self._redis.smembers(exec_key)  # type: ignore[misc]
        return [m.decode() if isinstance(m, bytes) else m for m in members]

    async def delete_tokens_for_execution(self, execution_id: str) -> int:
        """Delete all tokens for an execution."""
        token_ids = await self.get_tokens_for_execution(execution_id)
        if not token_ids:
            return 0

        keys = [f"{REDIS_TOKEN_PREFIX}{tid}" for tid in token_ids]
        await self._redis.delete(*keys)

        exec_key = f"{REDIS_EXECUTION_TOKENS_PREFIX}{execution_id}"
        await self._redis.delete(exec_key)

        logger.info(
            "Tokens revoked for execution (execution_id=%s, count=%d)",
            execution_id,
            len(token_ids),
        )
        return len(token_ids)
