"""In-memory workspace adapters for testing.

⚠️  TEST ENVIRONMENT ONLY ⚠️

All adapters in this module will raise TestEnvironmentRequiredError
if used outside of APP_ENVIRONMENT=test or APP_ENVIRONMENT=testing.

These adapters implement the port interfaces from aef_domain.contexts.workspaces:
- MemoryIsolationAdapter: IsolationBackendPort
- MemorySidecarAdapter: SidecarPort
- MemoryTokenInjectionAdapter: TokenInjectionPort
- MemoryArtifactAdapter: ArtifactCollectionPort
- MemoryEventStreamAdapter: EventStreamPort

Usage in tests:
    adapter = MemoryIsolationAdapter()
    handle = await adapter.create(config)
    result = await adapter.execute(handle, ["echo", "hello"])
    await adapter.destroy(handle)

See ADR-004 (Mock Objects: Test Environment Only) and ADR-023 (Workspace-First Execution).
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from aef_domain.contexts.workspaces._shared.value_objects import (
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
# EXCEPTIONS
# =============================================================================


class TestEnvironmentRequiredError(Exception):
    """Raised when in-memory adapters are used outside test environment.

    Per ADR-004 and ADR-023, mock/memory objects can only be used
    when APP_ENVIRONMENT is 'test' or 'testing'.
    """

    pass


# =============================================================================
# ENVIRONMENT VALIDATION
# =============================================================================


def _assert_test_environment() -> None:
    """Assert we're in test environment - memory adapters are TEST-ONLY.

    Per ADR-004 (Mock Objects: Test Environment Only):
    - All mock objects MUST validate they are running in test environment
    - This prevents accidental mock usage in production
    - Forces real implementations for E2E testing
    - Fails fast with clear error messages

    Raises:
        TestEnvironmentRequiredError: If APP_ENVIRONMENT is not 'test' or 'testing'
    """
    app_env = os.getenv("APP_ENVIRONMENT", "development").lower()

    if app_env in ("test", "testing"):
        return  # OK

    raise TestEnvironmentRequiredError(
        f"Memory adapters cannot be used in '{app_env}' environment. "
        f"Memory adapters are for TESTS ONLY.\n\n"
        f"For development/production, use Docker adapters:\n"
        f"  from aef_adapters.workspace_backends.docker import DockerIsolationAdapter\n\n"
        f"To run tests, set APP_ENVIRONMENT=test:\n"
        f"  APP_ENVIRONMENT=test pytest ...\n\n"
        f"See ADR-004: Environment Configuration\n"
        f"See ADR-023: Workspace-First Execution Model"
    )


# =============================================================================
# IN-MEMORY STATE
# =============================================================================


@dataclass
class MemoryIsolationState:
    """State for an in-memory isolation instance."""

    isolation_id: str
    config: IsolationConfig
    files: dict[str, bytes] = field(default_factory=dict)
    environment: dict[str, str] = field(default_factory=dict)
    command_history: list[tuple[list[str], int, str, str]] = field(default_factory=list)
    is_healthy: bool = True
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class MemorySidecarState:
    """State for an in-memory sidecar instance."""

    sidecar_id: str
    proxy_url: str
    tokens: dict[str, str] = field(default_factory=dict)
    token_ttl: int = 300
    is_healthy: bool = True
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))


# =============================================================================
# MEMORY ISOLATION ADAPTER
# =============================================================================


class MemoryIsolationAdapter:
    """In-memory implementation of IsolationBackendPort.

    ⚠️  TEST ENVIRONMENT ONLY ⚠️

    Simulates isolation without Docker/VM overhead.
    Commands are recorded but not actually executed.

    Usage:
        adapter = MemoryIsolationAdapter()
        handle = await adapter.create(config)
        result = await adapter.execute(handle, ["echo", "hello"])
        await adapter.destroy(handle)
    """

    def __init__(self) -> None:
        """Initialize adapter - validates test environment."""
        _assert_test_environment()
        self._instances: dict[str, MemoryIsolationState] = {}

    async def create(self, config: IsolationConfig) -> IsolationHandle:
        """Create in-memory isolation instance.

        Args:
            config: Isolation configuration

        Returns:
            IsolationHandle for subsequent operations
        """
        from aef_domain.contexts.workspaces._shared.value_objects import IsolationHandle

        isolation_id = f"mem-{uuid.uuid4().hex[:12]}"

        state = MemoryIsolationState(
            isolation_id=isolation_id,
            config=config,
            environment=dict(config.environment) if config.environment else {},
        )
        self._instances[isolation_id] = state

        return IsolationHandle(
            isolation_id=isolation_id,
            isolation_type="memory",
            proxy_url=None,  # Set by sidecar if used
            workspace_path="/workspace",
        )

    async def destroy(self, handle: IsolationHandle) -> None:
        """Destroy in-memory isolation instance.

        Args:
            handle: Handle from create()
        """
        self._instances.pop(handle.isolation_id, None)

    async def execute(
        self,
        handle: IsolationHandle,
        command: list[str],
        *,
        _timeout_seconds: int | None = None,
        _working_directory: str | None = None,
        _environment: dict[str, str] | None = None,
    ) -> ExecutionResult:
        """Simulate command execution in memory.

        Records the command but doesn't actually execute it.
        Returns configurable mock result.

        Args:
            handle: Handle from create()
            command: Command to "execute"
            timeout_seconds: Ignored in mock
            working_directory: Ignored in mock
            environment: Additional environment variables

        Returns:
            ExecutionResult with mock values
        """
        from aef_domain.contexts.workspaces._shared.value_objects import ExecutionResult

        state = self._instances.get(handle.isolation_id)
        if state is None:
            return ExecutionResult(
                exit_code=1,
                success=False,
                duration_ms=0.0,
                stderr="Isolation not found",
            )

        # Record the command
        result_tuple = (0, "", "")  # Default: success with no output
        state.command_history.append((command, *result_tuple))

        return ExecutionResult(
            exit_code=0,
            success=True,
            duration_ms=1.0,  # Mock duration
            stdout="",
            stderr="",
            stdout_lines=0,
            stderr_lines=0,
            timed_out=False,
        )

    async def health_check(self, handle: IsolationHandle) -> bool:
        """Check if mock isolation is "healthy".

        Args:
            handle: Handle from create()

        Returns:
            True if instance exists and is_healthy flag is True
        """
        state = self._instances.get(handle.isolation_id)
        return state is not None and state.is_healthy

    # ==========================================================================
    # TEST HELPERS
    # ==========================================================================

    def get_command_history(self, handle: IsolationHandle) -> list[tuple[list[str], int, str, str]]:
        """Get command history for testing.

        Args:
            handle: Handle from create()

        Returns:
            List of (command, exit_code, stdout, stderr) tuples
        """
        state = self._instances.get(handle.isolation_id)
        return state.command_history if state else []

    def set_unhealthy(self, handle: IsolationHandle) -> None:
        """Mark isolation as unhealthy for testing.

        Args:
            handle: Handle from create()
        """
        state = self._instances.get(handle.isolation_id)
        if state:
            state.is_healthy = False


# =============================================================================
# MEMORY SIDECAR ADAPTER
# =============================================================================


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
        from aef_domain.contexts.workspaces._shared.value_objects import SidecarHandle

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


# =============================================================================
# MEMORY TOKEN INJECTION ADAPTER
# =============================================================================


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
        from aef_domain.contexts.workspaces._shared.value_objects import (
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


# =============================================================================
# MEMORY ARTIFACT ADAPTER
# =============================================================================


class MemoryArtifactAdapter:
    """In-memory implementation of ArtifactCollectionPort.

    ⚠️  TEST ENVIRONMENT ONLY ⚠️

    Simulates artifact collection without filesystem access.
    """

    def __init__(self) -> None:
        """Initialize adapter - validates test environment."""
        _assert_test_environment()
        self._artifacts: dict[str, list[Artifact]] = {}  # isolation_id -> artifacts

    async def collect(
        self,
        handle: IsolationHandle,
        _patterns: list[str],
        *,
        _destination: str | None = None,
    ) -> ArtifactCollectionResult:
        """Simulate artifact collection.

        Args:
            handle: Isolation handle
            patterns: Glob patterns (ignored in mock)
            destination: Destination path (ignored in mock)

        Returns:
            ArtifactCollectionResult with pre-configured artifacts
        """
        from aef_domain.contexts.workspaces._shared.value_objects import (
            ArtifactCollectionResult,
        )

        artifacts = self._artifacts.get(handle.isolation_id, [])

        return ArtifactCollectionResult(
            success=True,
            artifacts=tuple(artifacts),
            total_size_bytes=sum(a.size_bytes for a in artifacts),
        )

    async def list_artifacts(
        self,
        handle: IsolationHandle,
        _path: str = "/workspace",
    ) -> list[Artifact]:
        """List mock artifacts.

        Args:
            handle: Isolation handle
            path: Directory path (ignored in mock)

        Returns:
            Pre-configured artifact list
        """
        return self._artifacts.get(handle.isolation_id, [])

    def add_artifact(self, handle: IsolationHandle, artifact: Artifact) -> None:
        """Add artifact for testing.

        Args:
            handle: Isolation handle
            artifact: Artifact to add
        """
        if handle.isolation_id not in self._artifacts:
            self._artifacts[handle.isolation_id] = []
        self._artifacts[handle.isolation_id].append(artifact)


# =============================================================================
# MEMORY EVENT STREAM ADAPTER
# =============================================================================


class MemoryEventStreamAdapter:
    """In-memory implementation of EventStreamPort.

    ⚠️  TEST ENVIRONMENT ONLY ⚠️

    Simulates event streaming with configurable output.
    """

    def __init__(self) -> None:
        """Initialize adapter - validates test environment."""
        _assert_test_environment()
        self._streams: dict[str, list[str]] = {}  # isolation_id -> lines

    async def stream(
        self,
        handle: IsolationHandle,
        _command: list[str],
        *,
        _timeout_seconds: int | None = None,
    ) -> AsyncIterator[str]:
        """Stream mock output lines.

        Args:
            handle: Isolation handle
            command: Command to execute (ignored)
            timeout_seconds: Timeout (ignored)

        Yields:
            Pre-configured output lines
        """
        lines = self._streams.get(handle.isolation_id, [])
        for line in lines:
            yield line

    def set_stream_output(self, handle: IsolationHandle, lines: list[str]) -> None:
        """Configure stream output for testing.

        Args:
            handle: Isolation handle
            lines: Lines to yield when stream() is called
        """
        self._streams[handle.isolation_id] = lines
