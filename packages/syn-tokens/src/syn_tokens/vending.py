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

import logging
import secrets
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from syn_tokens.models import ScopedToken, TokenScope, TokenType
from syn_tokens.singletons import configure_redis_token_vending as configure_redis
from syn_tokens.singletons import (
    get_token_vending_service as get_token_vending_service,
)
from syn_tokens.singletons import (
    reset_token_vending_service as reset_token_vending_service,
)
from syn_tokens.token_stores import InMemoryTokenStore as InMemoryTokenStore
from syn_tokens.token_stores import RedisTokenStore as RedisTokenStore

if TYPE_CHECKING:
    from syn_tokens.token_stores import (
        TokenStore,
    )

logger = logging.getLogger(__name__)

# Default token TTL (5 minutes)
DEFAULT_TOKEN_TTL_SECONDS = 5 * 60

# Token ID prefix for easy identification
TOKEN_ID_PREFIX = "syn-tok-"


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
        tenant_id: str | None = None,
    ) -> ScopedToken:
        """Issue a new scoped token.

        Args:
            execution_id: The execution this token is for
            token_type: Type of token (anthropic, github, internal)
            scope: Scope restrictions (defaults to empty scope)
            ttl_seconds: Token TTL in seconds (defaults to 5 minutes)
            tenant_id: Optional tenant ID for multi-tenancy

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
            tenant_id=tenant_id,
        )

        await self._store.store(token)

        logger.info(
            "Token vended (token_id=%s, execution_id=%s, type=%s, tenant=%s, ttl=%ds)",
            token.token_id,
            execution_id,
            token_type.value,
            tenant_id or "default",
            ttl,
        )

        return token

    async def vend_execution_tokens(
        self,
        execution_id: str,
        tenant_id: str | None = None,
        token_types: list[TokenType] | None = None,
        scope: TokenScope | None = None,
        ttl_seconds: int | None = None,
    ) -> dict[TokenType, ScopedToken]:
        """Vend multiple tokens for an execution (convenience method).

        This is typically called when starting a phase to pre-vend all
        required tokens before the agent starts.

        Args:
            execution_id: The execution ID
            tenant_id: Optional tenant ID for multi-tenancy
            token_types: Token types to vend (defaults to ANTHROPIC)
            scope: Scope restrictions applied to all tokens
            ttl_seconds: TTL for all tokens

        Returns:
            Dict mapping token type to issued token
        """
        types = token_types or [TokenType.ANTHROPIC]
        tokens = {}

        for token_type in types:
            token = await self.vend_token(
                execution_id=execution_id,
                token_type=token_type,
                scope=scope,
                ttl_seconds=ttl_seconds,
                tenant_id=tenant_id,
            )
            tokens[token_type] = token

        return tokens

    async def get_tokens_by_tenant(self, tenant_id: str) -> list[ScopedToken]:
        """Get all active tokens for a tenant."""
        from syn_tokens.tenant_ops import get_tokens_by_tenant

        return await get_tokens_by_tenant(self._store, tenant_id)

    async def revoke_tokens_for_tenant(self, tenant_id: str) -> int:
        """Revoke all tokens for a tenant."""
        from syn_tokens.tenant_ops import revoke_tokens_for_tenant

        return await revoke_tokens_for_tenant(self._store, tenant_id)

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
            logger.info("Token revoked (token_id=%s)", token_id)
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

    def _generate_token_id(self) -> str:
        """Generate a unique token ID."""
        return f"{TOKEN_ID_PREFIX}{secrets.token_urlsafe(24)}"
