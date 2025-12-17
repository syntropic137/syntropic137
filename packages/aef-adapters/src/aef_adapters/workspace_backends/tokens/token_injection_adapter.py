"""Token injection adapter via sidecar proxy.

Composes TokenVendingPort and SidecarPort to inject tokens into workspaces
following the zero-trust architecture from ADR-022.

See ADR-022: Secure Token Architecture
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aef_adapters.workspace_backends.tokens.token_vending_adapter import (
        TokenVendingServiceAdapter,
    )
    from aef_domain.contexts.workspaces._shared.ports import SidecarPort
    from aef_domain.contexts.workspaces._shared.value_objects import (
        IsolationHandle,
        SidecarHandle,
        TokenInjectionResult,
        TokenType,
    )

logger = logging.getLogger(__name__)


class SidecarTokenInjectionAdapter:
    """Injects tokens into workspace via sidecar proxy.

    Implements TokenInjectionPort from the workspace domain.

    This is the preferred method for token injection because:
    - Tokens never enter the workspace filesystem
    - Sidecar intercepts HTTP requests and injects headers
    - Zero-trust: workspace can't see or leak tokens

    Architecture:
        ┌─────────────┐     ┌─────────────────┐     ┌─────────────┐
        │  Workspace  │────▶│  Sidecar Proxy  │────▶│   API       │
        │  (no token) │     │  (injects auth) │     │  (Anthropic)│
        └─────────────┘     └─────────────────┘     └─────────────┘
                                    │
                             Token Vending
                               Service

    Usage:
        vending = TokenVendingServiceAdapter(token_service)
        sidecar = DockerSidecarAdapter()
        injection = SidecarTokenInjectionAdapter(vending, sidecar)

        # Inject tokens during workspace setup
        result = await injection.inject(
            handle=isolation_handle,
            execution_id="exec-123",
            token_types=[TokenType.ANTHROPIC, TokenType.GITHUB],
            sidecar_handle=sidecar_handle,
        )
    """

    def __init__(
        self,
        vending_adapter: TokenVendingServiceAdapter,
        sidecar_adapter: SidecarPort,
    ) -> None:
        """Initialize injection adapter.

        Args:
            vending_adapter: Adapter for vending tokens
            sidecar_adapter: Adapter for configuring sidecar proxy
        """
        self._vending = vending_adapter
        self._sidecar = sidecar_adapter

    async def inject(
        self,
        _handle: IsolationHandle,  # Not used - sidecar handles injection
        execution_id: str,
        token_types: list[TokenType],
        *,
        sidecar_handle: SidecarHandle,
        ttl_seconds: int = 300,
    ) -> TokenInjectionResult:
        """Inject tokens into workspace via sidecar.

        Steps:
        1. Vend tokens from TokenVendingService
        2. Configure sidecar to inject these tokens into requests

        Args:
            handle: Isolation handle (workspace container)
            execution_id: Execution ID for audit
            token_types: Types of tokens to inject
            sidecar_handle: Sidecar proxy handle
            ttl_seconds: Token validity duration

        Returns:
            TokenInjectionResult with injection details
        """
        from aef_domain.contexts.workspaces._shared.value_objects import (
            InjectionMethod,
            TokenInjectionResult,
        )

        # Step 1: Vend all required tokens
        tokens = await self._vending.vend_tokens(
            token_types=token_types,
            execution_id=execution_id,
            ttl_seconds=ttl_seconds,
        )

        # Step 2: Configure sidecar with these tokens
        await self._sidecar.configure_tokens(
            handle=sidecar_handle,
            tokens=tokens,
            ttl_seconds=ttl_seconds,
        )

        logger.info(
            "Tokens injected via sidecar (execution=%s, types=%s)",
            execution_id,
            [t.value for t in token_types],
        )

        return TokenInjectionResult(
            success=True,
            tokens_injected=tuple(token_types),
            injection_method=InjectionMethod.SIDECAR,
            ttl_seconds=ttl_seconds,
        )

    async def revoke(self, execution_id: str) -> None:
        """Revoke all injected tokens.

        Called during workspace cleanup.

        Args:
            execution_id: Execution ID
        """
        await self._vending.revoke_tokens(execution_id)
        logger.info("Tokens revoked for execution: %s", execution_id)


class DirectTokenInjectionAdapter:
    """Injects tokens directly via environment variables.

    ⚠️  LEGACY / LESS SECURE - Prefer SidecarTokenInjectionAdapter

    This method exposes tokens to the workspace process, which is
    less secure than sidecar injection. Use only when sidecar is
    not available.

    Tokens are injected as environment variables:
    - ANTHROPIC_API_KEY
    - GITHUB_TOKEN
    """

    def __init__(self, vending_adapter: TokenVendingServiceAdapter) -> None:
        """Initialize direct injection adapter.

        Args:
            vending_adapter: Adapter for vending tokens
        """
        self._vending = vending_adapter

    async def inject(
        self,
        _handle: IsolationHandle,  # Not used - env vars set at creation time
        execution_id: str,
        token_types: list[TokenType],
        *,
        ttl_seconds: int = 300,
    ) -> TokenInjectionResult:
        """Inject tokens as environment variables.

        ⚠️  Less secure than sidecar injection.

        Args:
            handle: Isolation handle
            execution_id: Execution ID
            token_types: Token types to inject
            ttl_seconds: Token validity duration

        Returns:
            TokenInjectionResult with environment variable names
        """
        from aef_domain.contexts.workspaces._shared.value_objects import (
            InjectionMethod,
            TokenInjectionResult,
            TokenType,
        )

        # Vend tokens
        tokens = await self._vending.vend_tokens(
            token_types=token_types,
            execution_id=execution_id,
            ttl_seconds=ttl_seconds,
        )

        # Map to environment variables
        env_mapping = {
            TokenType.ANTHROPIC: "ANTHROPIC_API_KEY",
            TokenType.GITHUB: "GITHUB_TOKEN",
        }

        env_vars = {}
        for token_type, token_value in tokens.items():
            env_name = env_mapping.get(token_type)
            if env_name:
                env_vars[env_name] = token_value

        logger.warning(
            "Tokens injected via env vars (LESS SECURE): execution=%s, vars=%s",
            execution_id,
            list(env_vars.keys()),
        )

        return TokenInjectionResult(
            success=True,
            tokens_injected=tuple(token_types),
            injection_method=InjectionMethod.ENV_VAR,
            ttl_seconds=ttl_seconds,
        )

    async def revoke(self, execution_id: str) -> None:
        """Revoke tokens (env vars cannot be unset in running process)."""
        await self._vending.revoke_tokens(execution_id)
