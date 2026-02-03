"""Tests for token adapters.

Run: pytest packages/aef-adapters/src/aef_adapters/workspace_backends/tokens/test_token_adapters.py -v
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from aef_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
    InjectionMethod,
    IsolationHandle,
    SidecarHandle,
    TokenType,
)
from aef_tokens.models import TokenType as AefTokenType
from aef_tokens.vending import InMemoryTokenStore, TokenVendingService

# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def token_service() -> TokenVendingService:
    """Create in-memory token vending service."""
    store = InMemoryTokenStore()
    return TokenVendingService(store, default_ttl_seconds=300)


@pytest.fixture
def isolation_handle() -> IsolationHandle:
    """Create test isolation handle."""
    return IsolationHandle(
        isolation_id="container-123",
        isolation_type="docker",
        workspace_path="/workspace",
    )


@pytest.fixture
def sidecar_handle() -> SidecarHandle:
    """Create test sidecar handle."""
    return SidecarHandle(
        sidecar_id="sidecar-456",
        proxy_url="http://sidecar-456:8080",
        started_at=datetime.now(UTC),
    )


# =============================================================================
# TOKEN VENDING ADAPTER TESTS
# =============================================================================


@pytest.mark.integration
class TestTokenVendingServiceAdapter:
    """Tests for TokenVendingServiceAdapter."""

    @pytest.mark.asyncio
    async def test_vend_token_returns_token_id(self, token_service: TokenVendingService) -> None:
        """Test that vend_token returns a token ID."""
        from aef_adapters.workspace_backends.tokens import TokenVendingServiceAdapter

        adapter = TokenVendingServiceAdapter(token_service)

        token_id = await adapter.vend_token(
            token_type=TokenType.ANTHROPIC,
            execution_id="exec-123",
            ttl_seconds=300,
        )

        assert token_id.startswith("aef-tok-")

    @pytest.mark.asyncio
    async def test_vend_token_stores_in_service(self, token_service: TokenVendingService) -> None:
        """Test that vended token is stored in service."""
        from aef_adapters.workspace_backends.tokens import TokenVendingServiceAdapter

        adapter = TokenVendingServiceAdapter(token_service)

        token_id = await adapter.vend_token(
            token_type=TokenType.ANTHROPIC,
            execution_id="exec-123",
            ttl_seconds=300,
        )

        # Verify token exists in service
        stored_token = await token_service.get_token(token_id)
        assert stored_token is not None
        assert stored_token.execution_id == "exec-123"
        assert stored_token.token_type == AefTokenType.ANTHROPIC

    @pytest.mark.asyncio
    async def test_vend_tokens_returns_multiple(self, token_service: TokenVendingService) -> None:
        """Test vending multiple tokens at once."""
        from aef_adapters.workspace_backends.tokens import TokenVendingServiceAdapter

        adapter = TokenVendingServiceAdapter(token_service)

        tokens = await adapter.vend_tokens(
            token_types=[TokenType.ANTHROPIC, TokenType.GITHUB],
            execution_id="exec-multi",
            ttl_seconds=300,
        )

        assert len(tokens) == 2
        assert TokenType.ANTHROPIC in tokens
        assert TokenType.GITHUB in tokens

    @pytest.mark.asyncio
    async def test_revoke_tokens_removes_all(self, token_service: TokenVendingService) -> None:
        """Test that revoke_tokens removes all tokens for execution."""
        from aef_adapters.workspace_backends.tokens import TokenVendingServiceAdapter

        adapter = TokenVendingServiceAdapter(token_service)

        # Vend some tokens
        token_id = await adapter.vend_token(
            token_type=TokenType.ANTHROPIC,
            execution_id="exec-revoke",
        )

        # Revoke
        await adapter.revoke_tokens("exec-revoke")

        # Verify token is gone
        stored = await token_service.get_token(token_id)
        assert stored is None

    @pytest.mark.asyncio
    async def test_validate_token_returns_valid(self, token_service: TokenVendingService) -> None:
        """Test token validation for valid token."""
        from aef_adapters.workspace_backends.tokens import TokenVendingServiceAdapter

        adapter = TokenVendingServiceAdapter(token_service)

        token_id = await adapter.vend_token(
            token_type=TokenType.ANTHROPIC,
            execution_id="exec-validate",
        )

        is_valid, error = await adapter.validate_token(token_id)

        assert is_valid is True
        assert error is None

    @pytest.mark.asyncio
    async def test_validate_token_returns_invalid_for_missing(
        self, token_service: TokenVendingService
    ) -> None:
        """Test token validation for missing token."""
        from aef_adapters.workspace_backends.tokens import TokenVendingServiceAdapter

        adapter = TokenVendingServiceAdapter(token_service)

        is_valid, error = await adapter.validate_token("nonexistent-token")

        assert is_valid is False
        assert "not found" in error.lower()


# =============================================================================
# SIDECAR TOKEN INJECTION ADAPTER TESTS
# =============================================================================


class TestSidecarTokenInjectionAdapter:
    """Tests for SidecarTokenInjectionAdapter."""

    @pytest.mark.asyncio
    async def test_inject_vends_and_configures(
        self,
        token_service: TokenVendingService,
        isolation_handle: IsolationHandle,
        sidecar_handle: SidecarHandle,
    ) -> None:
        """Test that inject vends tokens and configures sidecar."""
        from aef_adapters.workspace_backends.tokens import (
            SidecarTokenInjectionAdapter,
            TokenVendingServiceAdapter,
        )

        # Create mocks
        vending = TokenVendingServiceAdapter(token_service)
        sidecar = MagicMock()
        sidecar.configure_tokens = AsyncMock()

        adapter = SidecarTokenInjectionAdapter(vending, sidecar)

        result = await adapter.inject(
            isolation_handle,
            execution_id="exec-inject",
            token_types=[TokenType.ANTHROPIC],
            sidecar_handle=sidecar_handle,
        )

        # Verify result
        assert result.success is True
        assert result.injection_method == InjectionMethod.SIDECAR
        assert TokenType.ANTHROPIC in result.tokens_injected

        # Verify sidecar was configured
        sidecar.configure_tokens.assert_called_once()

    @pytest.mark.asyncio
    async def test_inject_multiple_token_types(
        self,
        token_service: TokenVendingService,
        isolation_handle: IsolationHandle,
        sidecar_handle: SidecarHandle,
    ) -> None:
        """Test injecting multiple token types."""
        from aef_adapters.workspace_backends.tokens import (
            SidecarTokenInjectionAdapter,
            TokenVendingServiceAdapter,
        )

        vending = TokenVendingServiceAdapter(token_service)
        sidecar = MagicMock()
        sidecar.configure_tokens = AsyncMock()

        adapter = SidecarTokenInjectionAdapter(vending, sidecar)

        result = await adapter.inject(
            isolation_handle,
            execution_id="exec-multi",
            token_types=[TokenType.ANTHROPIC, TokenType.GITHUB],
            sidecar_handle=sidecar_handle,
        )

        assert len(result.tokens_injected) == 2

        # Check sidecar received both tokens
        call_args = sidecar.configure_tokens.call_args
        tokens_dict = call_args.kwargs.get("tokens") or call_args.args[1]
        assert len(tokens_dict) == 2

    @pytest.mark.asyncio
    async def test_revoke_calls_vending_revoke(
        self,
        token_service: TokenVendingService,
        isolation_handle: IsolationHandle,
        sidecar_handle: SidecarHandle,
    ) -> None:
        """Test that revoke calls vending adapter."""
        from aef_adapters.workspace_backends.tokens import (
            SidecarTokenInjectionAdapter,
            TokenVendingServiceAdapter,
        )

        vending = TokenVendingServiceAdapter(token_service)
        sidecar = MagicMock()
        sidecar.configure_tokens = AsyncMock()

        adapter = SidecarTokenInjectionAdapter(vending, sidecar)

        # Inject first
        await adapter.inject(
            isolation_handle,
            execution_id="exec-revoke",
            token_types=[TokenType.ANTHROPIC],
            sidecar_handle=sidecar_handle,
        )

        # Revoke
        await adapter.revoke("exec-revoke")

        # Verify tokens are gone from service
        active = await token_service.get_active_tokens("exec-revoke")
        assert len(active) == 0


# =============================================================================
# DIRECT TOKEN INJECTION ADAPTER TESTS
# =============================================================================


class TestDirectTokenInjectionAdapter:
    """Tests for DirectTokenInjectionAdapter (legacy)."""

    @pytest.mark.asyncio
    async def test_inject_returns_env_var_method(
        self,
        token_service: TokenVendingService,
        isolation_handle: IsolationHandle,
    ) -> None:
        """Test that direct injection uses env var method."""
        from aef_adapters.workspace_backends.tokens import TokenVendingServiceAdapter
        from aef_adapters.workspace_backends.tokens.token_injection_adapter import (
            DirectTokenInjectionAdapter,
        )

        vending = TokenVendingServiceAdapter(token_service)
        adapter = DirectTokenInjectionAdapter(vending)

        result = await adapter.inject(
            isolation_handle,
            execution_id="exec-direct",
            token_types=[TokenType.ANTHROPIC],
        )

        assert result.success is True
        assert result.injection_method == InjectionMethod.ENV_VAR

    @pytest.mark.asyncio
    async def test_revoke_works(
        self,
        token_service: TokenVendingService,
        isolation_handle: IsolationHandle,
    ) -> None:
        """Test revoke for direct injection."""
        from aef_adapters.workspace_backends.tokens import TokenVendingServiceAdapter
        from aef_adapters.workspace_backends.tokens.token_injection_adapter import (
            DirectTokenInjectionAdapter,
        )

        vending = TokenVendingServiceAdapter(token_service)
        adapter = DirectTokenInjectionAdapter(vending)

        await adapter.inject(
            isolation_handle,
            execution_id="exec-direct-revoke",
            token_types=[TokenType.ANTHROPIC],
        )

        # Should not raise
        await adapter.revoke("exec-direct-revoke")


# =============================================================================
# INTEGRATION: Full Token Flow
# =============================================================================


class TestTokenFlowIntegration:
    """Integration tests for full token lifecycle."""

    @pytest.mark.asyncio
    async def test_full_token_lifecycle(
        self,
        token_service: TokenVendingService,
        isolation_handle: IsolationHandle,
        sidecar_handle: SidecarHandle,
    ) -> None:
        """Test complete lifecycle: vend -> inject -> use -> revoke."""
        from aef_adapters.workspace_backends.tokens import (
            SidecarTokenInjectionAdapter,
            TokenVendingServiceAdapter,
        )

        # Setup
        vending = TokenVendingServiceAdapter(token_service)
        sidecar = MagicMock()
        sidecar.configure_tokens = AsyncMock()
        injection = SidecarTokenInjectionAdapter(vending, sidecar)

        execution_id = "exec-lifecycle"

        # 1. Inject tokens
        result = await injection.inject(
            isolation_handle,
            execution_id=execution_id,
            token_types=[TokenType.ANTHROPIC, TokenType.GITHUB],
            sidecar_handle=sidecar_handle,
            ttl_seconds=300,
        )

        assert result.success is True
        assert len(result.tokens_injected) == 2

        # 2. Verify tokens exist and are valid
        active_tokens = await token_service.get_active_tokens(execution_id)
        assert len(active_tokens) == 2

        for token in active_tokens:
            is_valid, _ = await vending.validate_token(token.token_id)
            assert is_valid is True

        # 3. Revoke all tokens
        await injection.revoke(execution_id)

        # 4. Verify tokens are gone
        remaining = await token_service.get_active_tokens(execution_id)
        assert len(remaining) == 0
