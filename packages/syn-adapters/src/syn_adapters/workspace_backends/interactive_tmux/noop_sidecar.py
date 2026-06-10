"""NoopSidecarAdapter — production-safe no-op SidecarPort.

The interactive-tmux workspace path does NOT use the Envoy sidecar
(OAuth-on-disk authenticates outbound calls). The default
`MemorySidecarAdapter` is test-only (inherits `InMemoryAdapter` which
raises outside test/offline envs). This adapter exists so the
interactive-tmux factory can satisfy `WorkspaceService`'s typed
`SidecarPort` slot in production without injecting tokens.

All methods are inert. `start` returns a `SidecarHandle` with a
synthetic id so cleanup code can call `stop(handle)` uniformly without
branching on "did we even have a sidecar".
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
        IsolationHandle,
        SidecarConfig,
        SidecarHandle,
        TokenType,
    )


class NoopSidecarAdapter:
    """No-op SidecarPort implementation for OAuth-on-disk providers."""

    async def start(
        self,
        config: SidecarConfig,
        isolation_handle: IsolationHandle,
    ) -> SidecarHandle:
        from datetime import UTC, datetime

        from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
            SidecarHandle,
        )

        del config
        return SidecarHandle(
            sidecar_id=f"noop-{isolation_handle.isolation_id}",
            proxy_url="",
            started_at=datetime.now(UTC),
        )

    async def stop(self, handle: SidecarHandle) -> None:
        del handle

    async def configure_tokens(
        self,
        handle: SidecarHandle,
        tokens: dict[TokenType, str],
        ttl_seconds: int,
    ) -> None:
        del handle, tokens, ttl_seconds  # interactive-tmux uses OAuth on disk

    async def health_check(self, handle: SidecarHandle) -> bool:
        del handle
        return True
