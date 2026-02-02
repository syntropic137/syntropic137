"""Port interfaces for workspace bounded context.

This module defines the Dependency Injection (DI) boundaries for the workspace domain.
All external dependencies are abstracted behind Protocol interfaces.

Architecture (Hexagonal/Ports & Adapters):
    - Ports = Interfaces (defined here)
    - Adapters = Implementations (in aef_adapters.workspace_backends)

Each port represents a capability that can be provided by different backends:
    - IsolationBackendPort: Create/manage isolation (Docker, Firecracker, etc.)
    - SidecarPort: Manage sidecar proxy (token injection, egress filtering)
    - TokenVendingPort: Vend short-lived tokens (connects to aef-tokens)
    - ArtifactCollectionPort: Collect artifacts from workspace
    - EventStreamPort: Stream stdout from command execution

Usage:
    # In tests (with mocks)
    mock_isolation = Mock(spec=IsolationBackendPort)
    aggregate = WorkspaceAggregate(isolation_port=mock_isolation)

    # In production (use WorkspaceService)
    from aef_adapters.workspace_backends.service import WorkspaceService
    service = WorkspaceService.create()  # Uses agentic_isolation
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from aef_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
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
    """Port for creating/managing isolation environments.

    Implementations:
        - AgenticIsolationAdapter: Docker via agentic_isolation (recommended)
        - FirecrackerAdapter: Firecracker MicroVMs (future)
        - E2BAdapter: E2B cloud sandboxes (future)
        - MemoryIsolationAdapter: In-memory for testing

    Lifecycle:
        1. create(config) -> IsolationHandle
        2. execute(handle, command) -> ExecutionResult (repeatable)
        3. destroy(handle)
    """

    async def create(self, config: IsolationConfig) -> IsolationHandle:
        """Create isolation environment (container/VM).

        Args:
            config: Isolation configuration including backend, image, security policy

        Returns:
            IsolationHandle: Handle for subsequent operations

        Raises:
            IsolationCreationError: If creation fails
        """
        ...

    async def destroy(self, handle: IsolationHandle) -> None:
        """Destroy isolation environment.

        Cleans up all resources. Idempotent (safe to call multiple times).

        Args:
            handle: Handle from create()

        Raises:
            IsolationDestroyError: If destruction fails (resources may leak)
        """
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
        """Execute command inside isolation.

        Args:
            handle: Handle from create()
            command: Command to execute (e.g., ["python", "script.py"])
            timeout_seconds: Max execution time (None = use config default)
            working_directory: Working directory override
            environment: Additional environment variables

        Returns:
            ExecutionResult: Exit code, stdout, stderr, timing

        Raises:
            IsolationExecutionError: If execution fails to start
        """
        ...

    async def health_check(self, handle: IsolationHandle) -> bool:
        """Check if isolation is healthy and responsive.

        Args:
            handle: Handle from create()

        Returns:
            bool: True if isolation is healthy, False otherwise
        """
        ...

    async def copy_to(
        self,
        handle: IsolationHandle,
        files: list[tuple[str, bytes]],
        base_path: str = "/workspace",
    ) -> None:
        """Copy files into the isolation.

        Args:
            handle: Handle from create()
            files: List of (relative_path, content) tuples
            base_path: Base path inside isolation

        Raises:
            IsolationExecutionError: If copy fails
        """
        ...

    async def copy_from(
        self,
        handle: IsolationHandle,
        patterns: list[str],
        base_path: str = "/workspace",
    ) -> list[tuple[str, bytes]]:
        """Copy files out of the isolation.

        Args:
            handle: Handle from create()
            patterns: Glob patterns to match (e.g., ["artifacts/**/*"])
            base_path: Base path inside isolation

        Returns:
            List of (relative_path, content) tuples

        Raises:
            IsolationExecutionError: If copy fails
        """
        ...


# =============================================================================
# SIDECAR PORT
# =============================================================================


@runtime_checkable
class SidecarPort(Protocol):
    """Port for managing sidecar proxy (1:1 with workspace).

    The sidecar proxy handles:
    - Token injection into outbound requests (ADR-022)
    - Egress filtering (allowlist enforcement)
    - Rate limiting
    - Request/response logging for observability

    Implementations:
        - DockerSidecarAdapter: Docker-based Envoy sidecar
        - MemorySidecarAdapter: Mock for testing
    """

    async def start(
        self,
        config: SidecarConfig,
        isolation_handle: IsolationHandle,
    ) -> SidecarHandle:
        """Start sidecar proxy container.

        Creates a sidecar container networked with the isolation container.

        Args:
            config: Sidecar configuration
            isolation_handle: Handle to the main isolation container

        Returns:
            SidecarHandle: Handle for managing the sidecar

        Raises:
            SidecarStartError: If sidecar fails to start
        """
        ...

    async def stop(self, handle: SidecarHandle) -> None:
        """Stop sidecar proxy.

        Cleans up sidecar container. Idempotent.

        Args:
            handle: Handle from start()
        """
        ...

    async def configure_tokens(
        self,
        handle: SidecarHandle,
        tokens: dict[TokenType, str],
        ttl_seconds: int,
    ) -> None:
        """Configure tokens for injection by sidecar.

        Updates the sidecar's token store for request injection.

        Args:
            handle: Sidecar handle
            tokens: Token type -> token value mapping
            ttl_seconds: Token validity duration
        """
        ...

    async def health_check(self, handle: SidecarHandle) -> bool:
        """Check if sidecar is healthy.

        Args:
            handle: Sidecar handle

        Returns:
            bool: True if healthy
        """
        ...


# =============================================================================
# TOKEN VENDING PORT
# =============================================================================


@runtime_checkable
class TokenVendingPort(Protocol):
    """Port for vending short-lived tokens.

    Connects to the Token Vending Service (aef-tokens) to issue
    scoped, time-limited tokens for workspace use.

    Per ADR-022:
    - Tokens are never stored in workspace
    - Tokens are injected via sidecar proxy
    - Tokens are scoped to specific operations
    - Tokens have short TTL (minutes)

    Implementations:
        - TokenVendingServiceAdapter: Real service connection
        - MockTokenVendingAdapter: For testing
    """

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
            token_type: Type of token to vend (anthropic, github, etc.)
            execution_id: Execution ID for audit trail
            ttl_seconds: Token validity duration (default 5 minutes)
            scopes: Optional scope restrictions

        Returns:
            str: The token value

        Raises:
            TokenVendingError: If token cannot be vended
        """
        ...

    async def revoke_tokens(self, execution_id: str) -> None:
        """Revoke all tokens for an execution.

        Called during workspace cleanup.

        Args:
            execution_id: Execution ID
        """
        ...


# =============================================================================
# TOKEN INJECTION PORT
# =============================================================================


@runtime_checkable
class TokenInjectionPort(Protocol):
    """Port for injecting tokens into workspace.

    Combines TokenVendingPort and SidecarPort to inject tokens.

    Implementations:
        - SidecarTokenInjectionAdapter: Via sidecar proxy (preferred)
        - DirectTokenInjectionAdapter: Via env vars (legacy, less secure)
        - MockTokenInjectionAdapter: For testing
    """

    async def inject(
        self,
        handle: IsolationHandle,
        execution_id: str,
        token_types: list[TokenType],
        *,
        ttl_seconds: int = 300,
    ) -> TokenInjectionResult:
        """Inject tokens into workspace.

        Args:
            handle: Isolation handle
            execution_id: Execution ID for audit
            token_types: Types of tokens to inject
            ttl_seconds: Token validity duration

        Returns:
            TokenInjectionResult: Injection result with details
        """
        ...


# =============================================================================
# ARTIFACT COLLECTION PORT
# =============================================================================


@runtime_checkable
class ArtifactCollectionPort(Protocol):
    """Port for collecting artifacts from workspace.

    Collects files matching patterns from workspace for persistence.

    Implementations:
        - DockerArtifactAdapter: Collect via docker cp
        - S3ArtifactAdapter: Direct S3 upload from workspace
        - MemoryArtifactAdapter: In-memory for testing
    """

    async def collect(
        self,
        handle: IsolationHandle,
        patterns: list[str],
        *,
        destination: str | None = None,
    ) -> ArtifactCollectionResult:
        """Collect artifacts matching patterns.

        Args:
            handle: Isolation handle
            patterns: Glob patterns for files to collect (e.g., ["*.log", "output/*"])
            destination: Optional destination path/URL

        Returns:
            ArtifactCollectionResult: List of collected artifacts
        """
        ...

    async def list_artifacts(
        self,
        handle: IsolationHandle,
        path: str = "/workspace",
    ) -> list[Artifact]:
        """List available artifacts in workspace.

        Args:
            handle: Isolation handle
            path: Directory to list

        Returns:
            list[Artifact]: Available artifacts
        """
        ...


# =============================================================================
# EVENT STREAM PORT
# =============================================================================


@runtime_checkable
class EventStreamPort(Protocol):
    """Port for streaming events from workspace.

    Streams stdout from command execution for real-time processing.
    Used to capture agent runner events (JSONL format).

    Implementations:
        - AgenticEventStreamAdapter: Stream via agentic_isolation
        - MemoryEventStreamAdapter: Mock for testing
    """

    async def stream(
        self,
        handle: IsolationHandle,
        command: list[str],
        *,
        timeout_seconds: int | None = None,
        working_directory: str | None = None,
        environment: dict[str, str] | None = None,
    ) -> AsyncIterator[str]:
        """Stream stdout lines from command execution.

        Yields lines as they are produced by the command.

        Args:
            handle: Isolation handle
            command: Command to execute
            timeout_seconds: Max execution time

        Yields:
            str: Individual stdout lines

        Raises:
            StreamExecutionError: If streaming fails
        """
        ...


# =============================================================================
# GIT CONFIGURATION PORT
# =============================================================================


@runtime_checkable
class GitConfigurationPort(Protocol):
    """Port for configuring Git in workspace.

    Sets up git credentials, config, and clone operations.

    Implementations:
        - GitHubAppGitAdapter: Use GitHub App installation token
        - PatGitAdapter: Use Personal Access Token
        - MockGitAdapter: For testing
    """

    async def configure(
        self,
        handle: IsolationHandle,
        *,
        repo_url: str | None = None,
        branch: str = "main",
        user_name: str = "aef-agent",
        user_email: str = "agent@aef.local",
    ) -> None:
        """Configure git in workspace.

        Sets up git config and credentials.

        Args:
            handle: Isolation handle
            repo_url: Repository URL to clone (optional)
            branch: Branch to checkout
            user_name: Git user name
            user_email: Git user email
        """
        ...

    async def clone(
        self,
        handle: IsolationHandle,
        repo_url: str,
        *,
        branch: str = "main",
        destination: str = "/workspace",
    ) -> None:
        """Clone a repository into workspace.

        Args:
            handle: Isolation handle
            repo_url: Repository URL
            branch: Branch to checkout
            destination: Destination directory
        """
        ...

    async def push(
        self,
        handle: IsolationHandle,
        *,
        branch: str | None = None,
        message: str = "Agent commit",
    ) -> None:
        """Push changes from workspace.

        Args:
            handle: Isolation handle
            branch: Branch to push (None = current)
            message: Commit message if uncommitted changes
        """
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
