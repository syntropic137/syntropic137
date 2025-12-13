"""Token Vending Service for issuing short-lived, scoped tokens.

This service manages the lifecycle of scoped tokens:
- Issue tokens with TTL and scope restrictions
- Store tokens in Redis (or in-memory for testing)
- Revoke tokens on execution completion
- Track active tokens per execution

See Also:
    - docs/adrs/ADR-022-secure-token-architecture.md
"""

from __future__ import annotations

import json
import logging
import secrets
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Protocol

from aef_tokens.models import ScopedToken, TokenScope, TokenType

if TYPE_CHECKING:
    from redis.asyncio import Redis

logger = logging.getLogger(__name__)

# Default token TTL (5 minutes)
DEFAULT_TOKEN_TTL_SECONDS = 5 * 60

# Token ID prefix for easy identification
TOKEN_ID_PREFIX = "aef-tok-"

# Redis key prefixes
REDIS_TOKEN_PREFIX = "aef:token:"
REDIS_EXECUTION_TOKENS_PREFIX = "aef:exec-tokens:"


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


class RedisTokenStore:
    """Redis-backed token store with automatic TTL expiry."""

    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def store(self, token: ScopedToken) -> None:
        """Store a token with TTL."""
        key = f"{REDIS_TOKEN_PREFIX}{token.token_id}"
        exec_key = f"{REDIS_EXECUTION_TOKENS_PREFIX}{token.execution_id}"

        # Store token data with TTL
        await self._redis.setex(
            key,
            token.ttl_seconds,
            json.dumps(token.to_dict()),
        )

        # Add to execution's token set
        await self._redis.sadd(exec_key, token.token_id)
        # Set expiry on the set slightly longer than token TTL
        await self._redis.expire(exec_key, token.ttl_seconds + 60)

        logger.debug(
            "Token stored",
            token_id=token.token_id,
            execution_id=token.execution_id,
            ttl=token.ttl_seconds,
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
        members = await self._redis.smembers(exec_key)
        return [m.decode() if isinstance(m, bytes) else m for m in members]

    async def delete_tokens_for_execution(self, execution_id: str) -> int:
        """Delete all tokens for an execution."""
        token_ids = await self.get_tokens_for_execution(execution_id)

        if not token_ids:
            return 0

        # Delete all tokens
        keys = [f"{REDIS_TOKEN_PREFIX}{tid}" for tid in token_ids]
        await self._redis.delete(*keys)

        # Delete the execution's token set
        exec_key = f"{REDIS_EXECUTION_TOKENS_PREFIX}{execution_id}"
        await self._redis.delete(exec_key)

        logger.info(
            "Tokens revoked for execution",
            execution_id=execution_id,
            count=len(token_ids),
        )

        return len(token_ids)


class TokenVendingService:
    """Issues short-lived, scoped tokens for agent operations.

    Tokens have:
    - Short TTL (default 5 minutes)
    - Scope restrictions (APIs, repos, spend limits)
    - Automatic expiry via Redis TTL

    Example:
        service = TokenVendingService(store)

        # Issue a token for an execution
        token = await service.vend_token(
            execution_id="exec-123",
            token_type=TokenType.ANTHROPIC,
            scope=TokenScope(
                allowed_apis=["anthropic:messages"],
                max_cost_usd=Decimal("10.00"),
            ),
        )

        # Revoke all tokens when execution completes
        await service.revoke_tokens("exec-123")
    """

    def __init__(
        self,
        store: TokenStore,
        default_ttl_seconds: int = DEFAULT_TOKEN_TTL_SECONDS,
    ) -> None:
        """Initialize the token vending service.

        Args:
            store: Token storage backend
            default_ttl_seconds: Default TTL for tokens (5 minutes)
        """
        self._store = store
        self._default_ttl = default_ttl_seconds

    async def vend_token(
        self,
        execution_id: str,
        token_type: TokenType,
        scope: TokenScope | None = None,
        ttl_seconds: int | None = None,
    ) -> ScopedToken:
        """Issue a new scoped token.

        Args:
            execution_id: The execution this token is for
            token_type: Type of token (anthropic, github, internal)
            scope: Scope restrictions (defaults to empty scope)
            ttl_seconds: Token TTL in seconds (defaults to 5 minutes)

        Returns:
            The issued ScopedToken

        Raises:
            ValueError: If execution_id is empty
        """
        if not execution_id:
            msg = "execution_id is required"
            raise ValueError(msg)

        ttl = ttl_seconds or self._default_ttl
        now = datetime.now(UTC)

        token = ScopedToken(
            token_id=self._generate_token_id(),
            token_type=token_type,
            execution_id=execution_id,
            expires_at=now + timedelta(seconds=ttl),
            scope=scope or TokenScope(),
            created_at=now,
        )

        await self._store.store(token)

        logger.info(
            "Token vended",
            token_id=token.token_id,
            execution_id=execution_id,
            token_type=token_type.value,
            ttl_seconds=ttl,
        )

        return token

    async def get_token(self, token_id: str) -> ScopedToken | None:
        """Get a token by ID.

        Returns None if token doesn't exist or is expired.
        """
        return await self._store.get(token_id)

    async def validate_token(self, token_id: str) -> tuple[bool, str | None]:
        """Validate a token.

        Returns:
            Tuple of (is_valid, error_message)
        """
        token = await self._store.get(token_id)

        if token is None:
            return False, "Token not found or expired"

        if token.is_expired:
            return False, "Token expired"

        return True, None

    async def revoke_token(self, token_id: str) -> bool:
        """Revoke a single token.

        Returns True if token was revoked.
        """
        deleted = await self._store.delete(token_id)
        if deleted:
            logger.info("Token revoked", token_id=token_id)
        return deleted

    async def revoke_tokens(self, execution_id: str) -> int:
        """Revoke all tokens for an execution.

        Called when:
        - Execution completes
        - Execution fails
        - Admin intervention

        Returns:
            Number of tokens revoked
        """
        return await self._store.delete_tokens_for_execution(execution_id)

    async def get_active_tokens(self, execution_id: str) -> list[ScopedToken]:
        """Get all active (non-expired) tokens for an execution."""
        token_ids = await self._store.get_tokens_for_execution(execution_id)
        tokens = []

        for token_id in token_ids:
            token = await self._store.get(token_id)
            if token and not token.is_expired:
                tokens.append(token)

        return tokens

    async def vend_github_token(
        self,
        execution_id: str,
        ttl_seconds: int | None = None,
    ) -> str:
        """Vend a short-lived GitHub token for workspace injection.

        This is a convenience method that:
        1. Gets an installation token from GitHubAppClient
        2. Tracks it with the TokenVendingService (for revocation/audit)
        3. Returns the raw token value for git credential injection

        Args:
            execution_id: The execution this token is for
            ttl_seconds: Token TTL in seconds (defaults to 5 minutes)

        Returns:
            The raw GitHub installation token value

        Raises:
            ValueError: If GitHub App is not configured
        """
        # Import here to avoid circular dependency
        from aef_adapters.github import get_github_client

        client = get_github_client()

        # Get installation token from GitHub
        github_token = await client.get_installation_token()

        # Create a tracking record for this token
        # Note: We can't control the actual GitHub token expiry (1 hour),
        # but we track our intended TTL for revocation/audit purposes
        scoped_token = await self.vend_token(
            execution_id=execution_id,
            token_type=TokenType.GITHUB,
            scope=TokenScope(
                allowed_apis=["github:*"],
            ),
            ttl_seconds=ttl_seconds,
        )

        logger.info(
            "GitHub token vended",
            token_id=scoped_token.token_id,
            execution_id=execution_id,
            ttl_seconds=ttl_seconds or self._default_ttl,
        )

        return github_token

    def _generate_token_id(self) -> str:
        """Generate a unique token ID."""
        return f"{TOKEN_ID_PREFIX}{secrets.token_urlsafe(24)}"


# Singleton instance
_token_vending_service: TokenVendingService | None = None
_token_store: InMemoryTokenStore | RedisTokenStore | None = None


def get_token_vending_service() -> TokenVendingService:
    """Get the singleton token vending service.

    Uses in-memory store by default. Call configure_redis()
    to use Redis backend.
    """
    global _token_vending_service, _token_store

    if _token_vending_service is not None:
        return _token_vending_service

    # Default to in-memory store
    if _token_store is None:
        _token_store = InMemoryTokenStore()

    _token_vending_service = TokenVendingService(_token_store)
    logger.info("Token vending service initialized (in-memory)")

    return _token_vending_service


async def configure_redis(redis: Redis) -> TokenVendingService:
    """Configure the token vending service to use Redis.

    Args:
        redis: Redis async client

    Returns:
        Configured TokenVendingService
    """
    global _token_vending_service, _token_store

    _token_store = RedisTokenStore(redis)
    _token_vending_service = TokenVendingService(_token_store)
    logger.info("Token vending service initialized (Redis)")

    return _token_vending_service


def reset_token_vending_service() -> None:
    """Reset the singleton (for testing)."""
    global _token_vending_service, _token_store
    _token_vending_service = None
    if isinstance(_token_store, InMemoryTokenStore):
        _token_store.clear()
    _token_store = None
