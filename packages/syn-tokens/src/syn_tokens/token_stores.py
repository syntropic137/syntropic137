"""Token storage backends for the vending service."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from syn_tokens.models import ScopedToken

logger = logging.getLogger(__name__)

# Redis key prefixes
REDIS_TOKEN_PREFIX = "syn:token:"
REDIS_EXECUTION_TOKENS_PREFIX = "syn:exec-tokens:"


class TokenStore(Protocol):
    """Protocol for token storage backends."""

    async def store(self, token: ScopedToken) -> None:
        """Store a token with TTL."""
        ...

    async def get(self, token_id: str) -> ScopedToken | None:
        """Get a token by ID."""
        ...

    async def delete(self, token_id: str) -> bool:
        """Delete a token. Returns True if deleted."""
        ...

    async def get_tokens_for_execution(self, execution_id: str) -> list[str]:
        """Get all token IDs for an execution."""
        ...

    async def delete_tokens_for_execution(self, execution_id: str) -> int:
        """Delete all tokens for an execution. Returns count deleted."""
        ...


class InMemoryTokenStore:
    """In-memory token store for testing."""

    def __init__(self) -> None:
        self._tokens: dict[str, ScopedToken] = {}
        self._execution_tokens: dict[str, set[str]] = {}

    async def store(self, token: ScopedToken) -> None:
        """Store a token."""
        self._tokens[token.token_id] = token
        if token.execution_id not in self._execution_tokens:
            self._execution_tokens[token.execution_id] = set()
        self._execution_tokens[token.execution_id].add(token.token_id)

    async def get(self, token_id: str) -> ScopedToken | None:
        """Get a token by ID (returns None if expired)."""
        token = self._tokens.get(token_id)
        if token and token.is_expired:
            del self._tokens[token_id]
            return None
        return token

    async def delete(self, token_id: str) -> bool:
        """Delete a token."""
        if token_id in self._tokens:
            token = self._tokens.pop(token_id)
            if token.execution_id in self._execution_tokens:
                self._execution_tokens[token.execution_id].discard(token_id)
            return True
        return False

    async def get_tokens_for_execution(self, execution_id: str) -> list[str]:
        """Get all token IDs for an execution."""
        return list(self._execution_tokens.get(execution_id, set()))

    async def delete_tokens_for_execution(self, execution_id: str) -> int:
        """Delete all tokens for an execution."""
        token_ids = self._execution_tokens.pop(execution_id, set())
        for token_id in token_ids:
            self._tokens.pop(token_id, None)
        return len(token_ids)

    def clear(self) -> None:
        """Clear all tokens (for testing)."""
        self._tokens.clear()
        self._execution_tokens.clear()


from syn_tokens.redis_token_store import RedisTokenStore as RedisTokenStore  # noqa: E402
