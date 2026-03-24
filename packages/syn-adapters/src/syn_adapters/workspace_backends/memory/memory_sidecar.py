"""In-memory sidecar adapter for testing.

⚠️  TEST ENVIRONMENT ONLY ⚠️

See ADR-004 (Mock Objects: Test Environment Only) and ADR-023 (Workspace-First Execution).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from syn_adapters.workspace_backends.memory.memory_adapter import _assert_test_environment

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
        IsolationHandle,
        SidecarConfig,
        SidecarHandle,
        TokenType,
    )


@dataclass
class MemorySidecarState:
    """State for an in-memory sidecar instance."""

    sidecar_id: str
    proxy_url: str
    tokens: dict[str, str] = field(default_factory=dict)
    token_ttl: int = 300
    is_healthy: bool = True
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class MemorySidecarAdapter:
    """In-memory implementation of SidecarPort.

    ⚠️  TEST ENVIRONMENT ONLY ⚠️

    Simulates sidecar proxy without Docker overhead.
    """

    def __init__(self) -> None:
        """Initialize adapter - validates test environment."""
        _assert_test_environment()
        self._sidecars: dict[str, MemorySidecarState] = {}

    async def start(
        self,
        config: SidecarConfig,
        _isolation_handle: IsolationHandle,
    ) -> SidecarHandle:
        """Start mock sidecar.

        Args:
            config: Sidecar configuration
            isolation_handle: Handle to main isolation

        Returns:
            SidecarHandle for managing the mock sidecar
        """
        from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
            SidecarHandle,
        )

        sidecar_id = f"sidecar-{uuid.uuid4().hex[:8]}"
        proxy_url = f"http://localhost:{config.listen_port}"

        state = MemorySidecarState(
            sidecar_id=sidecar_id,
            proxy_url=proxy_url,
        )
        self._sidecars[sidecar_id] = state

        return SidecarHandle(
            sidecar_id=sidecar_id,
            proxy_url=proxy_url,
            started_at=datetime.now(UTC),
        )

    async def stop(self, handle: SidecarHandle) -> None:
        """Stop mock sidecar.

        Args:
            handle: Handle from start()
        """
        self._sidecars.pop(handle.sidecar_id, None)

    async def configure_tokens(
        self,
        handle: SidecarHandle,
        tokens: dict[TokenType, str],
        ttl_seconds: int,
    ) -> None:
        """Configure mock token injection.

        Args:
            handle: Sidecar handle
            tokens: Token type -> value mapping
            ttl_seconds: Token TTL
        """
        state = self._sidecars.get(handle.sidecar_id)
        if state:
            state.tokens = {str(k): v for k, v in tokens.items()}
            state.token_ttl = ttl_seconds

    async def health_check(self, handle: SidecarHandle) -> bool:
        """Check mock sidecar health.

        Args:
            handle: Sidecar handle

        Returns:
            True if sidecar exists and is healthy
        """
        state = self._sidecars.get(handle.sidecar_id)
        return state is not None and state.is_healthy
