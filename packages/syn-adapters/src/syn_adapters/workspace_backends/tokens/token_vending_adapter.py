"""Token Vending Service adapter.

Wraps the syn-tokens TokenVendingService to implement TokenVendingPort.

See ADR-022: Secure Token Architecture
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import TokenType
    from syn_tokens.vending import TokenVendingService

logger = logging.getLogger(__name__)


class TokenVendingServiceAdapter:
    """Adapter wrapping syn-tokens TokenVendingService.

    Implements TokenVendingPort from the workspace domain.

    Usage:
        from syn_tokens.vending import get_token_vending_service

        vending_service = get_token_vending_service()
        adapter = TokenVendingServiceAdapter(vending_service)

        token = await adapter.vend_token(
            token_type=TokenType.ANTHROPIC,
            execution_id="exec-123",
            ttl_seconds=300,
        )
    """

    def __init__(self, service: TokenVendingService) -> None:
        """Initialize adapter with TokenVendingService.

        Args:
            service: The underlying TokenVendingService from syn-tokens
        """
        self._service = service

    async def vend_token(
        self,
        token_type: TokenType,
        execution_id: str,
        *,
        ttl_seconds: int = 300,
        scopes: list[str] | None = None,
    ) -> str:
        """Vend a short-lived token for workspace use.

        Args:
            token_type: Type of token to vend
            execution_id: Execution ID for audit trail
            ttl_seconds: Token validity duration (default 5 minutes)
            scopes: Optional scope restrictions (not implemented yet)

        Returns:
            The token value (for injection into sidecar)

        Raises:
            ValueError: If execution_id is empty
        """
        from syn_tokens.models import TokenScope
        from syn_tokens.models import TokenType as SynTokenType

        # Map domain TokenType to syn-tokens TokenType
        syn_token_type = SynTokenType(token_type.value)

        # Create scope if provided
        scope = None
        if scopes:
            scope = TokenScope(allowed_apis=scopes)

        # Vend through service
        scoped_token = await self._service.vend_token(
            execution_id=execution_id,
            token_type=syn_token_type,
            scope=scope,
            ttl_seconds=ttl_seconds,
        )

        logger.info(
            "Token vended (type=%s, execution=%s, ttl=%ds)",
            token_type.value,
            execution_id,
            ttl_seconds,
        )

        # Return the token ID (the actual secret is stored in the service)
        # In a real system, you'd return the actual token value
        return scoped_token.token_id

    async def vend_tokens(
        self,
        token_types: list[TokenType],
        execution_id: str,
        *,
        ttl_seconds: int = 300,
    ) -> dict[TokenType, str]:
        """Vend multiple tokens at once.

        Convenience method for vending multiple token types.

        Args:
            token_types: Types of tokens to vend
            execution_id: Execution ID
            ttl_seconds: Token validity duration

        Returns:
            Dict mapping token type to token value
        """
        tokens = {}
        for token_type in token_types:
            token = await self.vend_token(
                token_type=token_type,
                execution_id=execution_id,
                ttl_seconds=ttl_seconds,
            )
            tokens[token_type] = token
        return tokens

    async def revoke_tokens(self, execution_id: str) -> None:
        """Revoke all tokens for an execution.

        Called during workspace cleanup.

        Args:
            execution_id: Execution ID
        """
        count = await self._service.revoke_tokens(execution_id)
        logger.info(
            "Tokens revoked (execution=%s, count=%d)",
            execution_id,
            count,
        )

    async def validate_token(self, token_id: str) -> tuple[bool, str | None]:
        """Validate a token.

        Args:
            token_id: Token ID to validate

        Returns:
            Tuple of (is_valid, error_message)
        """
        return await self._service.validate_token(token_id)
