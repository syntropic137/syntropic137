"""Tests for Token Vending Service."""

from decimal import Decimal

import pytest

from aef_tokens.models import TokenScope, TokenType
from aef_tokens.vending import (
    InMemoryTokenStore,
    TokenVendingService,
    reset_token_vending_service,
)


@pytest.fixture
def token_store() -> InMemoryTokenStore:
    """Create a fresh token store."""
    return InMemoryTokenStore()


@pytest.fixture
def vending_service(token_store: InMemoryTokenStore) -> TokenVendingService:
    """Create a vending service with in-memory store."""
    return TokenVendingService(token_store, default_ttl_seconds=300)


@pytest.fixture(autouse=True)
def reset_singleton() -> None:
    """Reset singleton after each test."""
    yield
    reset_token_vending_service()


class TestInMemoryTokenStore:
    """Tests for in-memory token store."""

    @pytest.mark.asyncio
    async def test_store_and_get(self, vending_service: TokenVendingService) -> None:
        """Should store and retrieve tokens."""
        token = await vending_service.vend_token(
            execution_id="exec-123",
            token_type=TokenType.ANTHROPIC,
        )

        retrieved = await vending_service.get_token(token.token_id)
        assert retrieved is not None
        assert retrieved.token_id == token.token_id
        assert retrieved.execution_id == "exec-123"

    @pytest.mark.asyncio
    async def test_get_returns_none_for_missing(self, vending_service: TokenVendingService) -> None:
        """Should return None for missing tokens."""
        result = await vending_service.get_token("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_delete(self, vending_service: TokenVendingService) -> None:
        """Should delete tokens."""
        token = await vending_service.vend_token(
            execution_id="exec-123",
            token_type=TokenType.ANTHROPIC,
        )

        deleted = await vending_service.revoke_token(token.token_id)
        assert deleted is True

        retrieved = await vending_service.get_token(token.token_id)
        assert retrieved is None

    @pytest.mark.asyncio
    async def test_get_tokens_for_execution(self, vending_service: TokenVendingService) -> None:
        """Should track tokens per execution."""
        # Vend multiple tokens for same execution
        token1 = await vending_service.vend_token(
            execution_id="exec-123",
            token_type=TokenType.ANTHROPIC,
        )
        token2 = await vending_service.vend_token(
            execution_id="exec-123",
            token_type=TokenType.GITHUB,
        )
        # Different execution
        await vending_service.vend_token(
            execution_id="exec-456",
            token_type=TokenType.ANTHROPIC,
        )

        active = await vending_service.get_active_tokens("exec-123")
        assert len(active) == 2
        token_ids = {t.token_id for t in active}
        assert token1.token_id in token_ids
        assert token2.token_id in token_ids

    @pytest.mark.asyncio
    async def test_delete_tokens_for_execution(self, vending_service: TokenVendingService) -> None:
        """Should delete all tokens for an execution."""
        # Vend multiple tokens
        await vending_service.vend_token(
            execution_id="exec-123",
            token_type=TokenType.ANTHROPIC,
        )
        await vending_service.vend_token(
            execution_id="exec-123",
            token_type=TokenType.GITHUB,
        )
        token_other = await vending_service.vend_token(
            execution_id="exec-456",
            token_type=TokenType.ANTHROPIC,
        )

        # Revoke all for exec-123
        count = await vending_service.revoke_tokens("exec-123")
        assert count == 2

        # exec-123 tokens gone
        active = await vending_service.get_active_tokens("exec-123")
        assert len(active) == 0

        # exec-456 token still exists
        other = await vending_service.get_token(token_other.token_id)
        assert other is not None


class TestTokenVendingService:
    """Tests for TokenVendingService."""

    @pytest.mark.asyncio
    async def test_vend_token_basic(self, vending_service: TokenVendingService) -> None:
        """Should vend a token with default scope."""
        token = await vending_service.vend_token(
            execution_id="exec-123",
            token_type=TokenType.ANTHROPIC,
        )

        assert token.token_id.startswith("aef-tok-")
        assert token.token_type == TokenType.ANTHROPIC
        assert token.execution_id == "exec-123"
        assert not token.is_expired
        assert token.scope.allowed_apis == []

    @pytest.mark.asyncio
    async def test_vend_token_with_scope(self, vending_service: TokenVendingService) -> None:
        """Should vend a token with custom scope."""
        scope = TokenScope(
            allowed_apis=["anthropic:messages"],
            allowed_repos=["org/repo"],
            max_cost_usd=Decimal("5.00"),
        )

        token = await vending_service.vend_token(
            execution_id="exec-123",
            token_type=TokenType.ANTHROPIC,
            scope=scope,
        )

        assert token.scope.allowed_apis == ["anthropic:messages"]
        assert token.scope.allowed_repos == ["org/repo"]
        assert token.scope.max_cost_usd == Decimal("5.00")

    @pytest.mark.asyncio
    async def test_vend_token_with_custom_ttl(self, vending_service: TokenVendingService) -> None:
        """Should vend a token with custom TTL."""
        token = await vending_service.vend_token(
            execution_id="exec-123",
            token_type=TokenType.GITHUB,
            ttl_seconds=3600,  # 1 hour
        )

        # Should expire in about 1 hour
        assert 3590 < token.seconds_until_expiry < 3610

    @pytest.mark.asyncio
    async def test_vend_token_requires_execution_id(
        self, vending_service: TokenVendingService
    ) -> None:
        """Should require execution_id."""
        with pytest.raises(ValueError, match="execution_id is required"):
            await vending_service.vend_token(
                execution_id="",
                token_type=TokenType.ANTHROPIC,
            )

    @pytest.mark.asyncio
    async def test_validate_token_valid(self, vending_service: TokenVendingService) -> None:
        """Should validate a valid token."""
        token = await vending_service.vend_token(
            execution_id="exec-123",
            token_type=TokenType.ANTHROPIC,
        )

        is_valid, error = await vending_service.validate_token(token.token_id)
        assert is_valid is True
        assert error is None

    @pytest.mark.asyncio
    async def test_validate_token_not_found(self, vending_service: TokenVendingService) -> None:
        """Should reject missing token."""
        is_valid, error = await vending_service.validate_token("nonexistent")
        assert is_valid is False
        assert "not found" in error.lower()

    @pytest.mark.asyncio
    async def test_unique_token_ids(self, vending_service: TokenVendingService) -> None:
        """Token IDs should be unique."""
        tokens = [
            await vending_service.vend_token(
                execution_id="exec-123",
                token_type=TokenType.ANTHROPIC,
            )
            for _ in range(100)
        ]

        token_ids = {t.token_id for t in tokens}
        assert len(token_ids) == 100  # All unique
