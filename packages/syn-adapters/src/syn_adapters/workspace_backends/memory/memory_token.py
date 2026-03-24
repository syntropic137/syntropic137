"""In-memory token injection adapter for testing.

⚠️  TEST ENVIRONMENT ONLY ⚠️

See ADR-004 (Mock Objects: Test Environment Only) and ADR-023 (Workspace-First Execution).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syn_adapters.workspace_backends.memory.memory_adapter import _assert_test_environment

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
        IsolationHandle,
        TokenInjectionResult,
        TokenType,
    )


class MemoryTokenInjectionAdapter:
    """In-memory implementation of TokenInjectionPort.

    ⚠️  TEST ENVIRONMENT ONLY ⚠️

    Simulates token injection without real token vending.
    """

    def __init__(self) -> None:
        """Initialize adapter - validates test environment."""
        _assert_test_environment()
        self._injections: dict[str, list[str]] = {}  # isolation_id -> token_types

    async def inject(
        self,
        handle: IsolationHandle,
        _execution_id: str,
        token_types: list[TokenType],
        *,
        ttl_seconds: int = 300,
    ) -> TokenInjectionResult:
        """Simulate token injection.

        Args:
            handle: Isolation handle
            execution_id: Execution ID for audit
            token_types: Types of tokens to inject
            ttl_seconds: Token TTL

        Returns:
            TokenInjectionResult indicating success
        """
        from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
            InjectionMethod,
            TokenInjectionResult,
        )

        self._injections[handle.isolation_id] = [str(t) for t in token_types]

        return TokenInjectionResult(
            success=True,
            tokens_injected=tuple(token_types),
            injection_method=InjectionMethod.SIDECAR,
            ttl_seconds=ttl_seconds,
        )

    def get_injected_tokens(self, handle: IsolationHandle) -> list[str]:
        """Get injected token types for testing.

        Args:
            handle: Isolation handle

        Returns:
            List of token type strings
        """
        return self._injections.get(handle.isolation_id, [])
