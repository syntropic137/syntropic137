"""Port interfaces for workspace bounded context.

Hexagonal/Ports & Adapters: Ports defined here, adapters in syn_adapters.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
        Artifact,
        ArtifactCollectionResult,
        ExecutionResult,
        IsolationConfig,
        IsolationHandle,
        SidecarConfig,
        SidecarHandle,
        TokenInjectionResult,
        TokenType,
    )


# =============================================================================
# ISOLATION BACKEND PORT
# =============================================================================


@runtime_checkable
class IsolationBackendPort(Protocol):
    """Port for creating/managing isolation environments."""

    async def create(self, config: IsolationConfig) -> IsolationHandle:
        """Create isolation environment (container/VM)."""
        ...

    async def destroy(self, handle: IsolationHandle) -> None:
        """Destroy isolation environment. Idempotent."""
        ...

    async def execute(
        self,
        handle: IsolationHandle,
        command: list[str],
        *,
        timeout_seconds: int | None = None,
        working_directory: str | None = None,
        environment: dict[str, str] | None = None,
    ) -> ExecutionResult:
        """Execute command inside isolation."""
        ...

    async def health_check(self, handle: IsolationHandle) -> bool:
        """Check if isolation is healthy and responsive."""
        ...

    async def copy_to(
        self,
        handle: IsolationHandle,
        files: list[tuple[str, bytes]],
        base_path: str = "/workspace",
    ) -> None:
        """Copy files into the isolation."""
        ...

    async def copy_from(
        self,
        handle: IsolationHandle,
        patterns: list[str],
        base_path: str = "/workspace",
    ) -> list[tuple[str, bytes]]:
        """Copy files out of the isolation."""
        ...


# =============================================================================
# SIDECAR PORT
# =============================================================================


@runtime_checkable
class SidecarPort(Protocol):
    """Port for managing sidecar proxy (1:1 with workspace)."""

    async def start(
        self,
        config: SidecarConfig,
        isolation_handle: IsolationHandle,
    ) -> SidecarHandle:
        """Start sidecar proxy container."""
        ...

    async def stop(self, handle: SidecarHandle) -> None:
        """Stop sidecar proxy. Idempotent."""
        ...

    async def configure_tokens(
        self,
        handle: SidecarHandle,
        tokens: dict[TokenType, str],
        ttl_seconds: int,
    ) -> None:
        """Configure tokens for injection by sidecar."""
        ...

    async def health_check(self, handle: SidecarHandle) -> bool:
        """Check if sidecar is healthy."""
        ...


# =============================================================================
# TOKEN VENDING PORT
# =============================================================================


@runtime_checkable
class TokenVendingPort(Protocol):
    """Port for vending short-lived tokens (ADR-022)."""

    async def vend_token(
        self,
        token_type: TokenType,
        execution_id: str,
        *,
        ttl_seconds: int = 300,
        scopes: list[str] | None = None,
    ) -> str:
        """Vend a short-lived, scoped token for workspace use."""
        ...

    async def revoke_tokens(self, execution_id: str) -> None:
        """Revoke all tokens for an execution."""
        ...


# =============================================================================
# TOKEN INJECTION PORT
# =============================================================================


@runtime_checkable
class TokenInjectionPort(Protocol):
    """Port for injecting tokens into workspace."""

    async def inject(
        self,
        handle: IsolationHandle,
        execution_id: str,
        token_types: list[TokenType],
        *,
        ttl_seconds: int = 300,
    ) -> TokenInjectionResult:
        """Inject tokens into workspace."""
        ...


# =============================================================================
# ARTIFACT COLLECTION PORT
# =============================================================================


@runtime_checkable
class ArtifactCollectionPort(Protocol):
    """Port for collecting artifacts from workspace."""

    async def collect(
        self,
        handle: IsolationHandle,
        patterns: list[str],
        *,
        destination: str | None = None,
    ) -> ArtifactCollectionResult:
        """Collect artifacts matching patterns."""
        ...

    async def list_artifacts(
        self,
        handle: IsolationHandle,
        path: str = "/workspace",
    ) -> list[Artifact]:
        """List available artifacts in workspace."""
        ...


# =============================================================================
# EVENT STREAM PORT
# =============================================================================


@runtime_checkable
class EventStreamPort(Protocol):
    """Port for streaming stdout from command execution (JSONL events)."""

    async def stream(
        self,
        handle: IsolationHandle,
        command: list[str],
        *,
        timeout_seconds: int | None = None,
        working_directory: str | None = None,
        environment: dict[str, str] | None = None,
    ) -> AsyncIterator[str]:
        """Stream stdout lines from command execution."""
        ...

    @property
    def last_exit_code(self) -> int | None:
        """Exit code from the most recent stream() call."""
        ...


# =============================================================================
# GIT CONFIGURATION PORT
# =============================================================================


@runtime_checkable
class GitConfigurationPort(Protocol):
    """Port for configuring Git in workspace."""

    async def configure(
        self,
        handle: IsolationHandle,
        *,
        repo_url: str | None = None,
        branch: str = "main",
        user_name: str = "syn-agent",
        user_email: str = "agent@syntropic137.com",
    ) -> None:
        """Configure git in workspace."""
        ...

    async def clone(
        self,
        handle: IsolationHandle,
        repo_url: str,
        *,
        branch: str = "main",
        destination: str = "/workspace",
    ) -> None:
        """Clone a repository into workspace."""
        ...

    async def push(
        self,
        handle: IsolationHandle,
        *,
        branch: str | None = None,
        message: str = "Agent commit",
    ) -> None:
        """Push changes from workspace."""
        ...


# =============================================================================
# EXCEPTIONS
# =============================================================================


class WorkspacePortError(Exception):
    """Base exception for port errors."""

    pass


class IsolationCreationError(WorkspacePortError):
    """Failed to create isolation environment."""

    pass


class IsolationDestroyError(WorkspacePortError):
    """Failed to destroy isolation environment."""

    pass


class IsolationExecutionError(WorkspacePortError):
    """Failed to execute command in isolation."""

    pass


class SidecarStartError(WorkspacePortError):
    """Failed to start sidecar proxy."""

    pass


class TokenVendingError(WorkspacePortError):
    """Failed to vend token."""

    pass


class StreamExecutionError(WorkspacePortError):
    """Failed to stream command output."""

    pass
