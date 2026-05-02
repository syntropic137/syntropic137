"""In-memory isolation adapter for testing.

⚠️  TEST ENVIRONMENT ONLY ⚠️

See ADR-060 (docs/adrs/ADR-060-restart-safe-trigger-deduplication.md).

Usage in tests:
    adapter = MemoryIsolationAdapter()
    handle = await adapter.create(config)
    result = await adapter.execute(handle, ["echo", "hello"])
    await adapter.destroy(handle)
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from syn_adapters.in_memory import InMemoryAdapter, InMemoryAdapterError

# Re-export for backwards compatibility with existing tests/imports
TestEnvironmentRequiredError = InMemoryAdapterError

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
        ExecutionResult,
        IsolationConfig,
        IsolationHandle,
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


# =============================================================================
# MEMORY ISOLATION ADAPTER
# =============================================================================


class MemoryIsolationAdapter(InMemoryAdapter):
    """In-memory implementation of IsolationBackendPort.

    ⚠️  TEST ENVIRONMENT ONLY ⚠️

    Simulates isolation without Docker/VM overhead.
    Commands are recorded but not actually executed.
    Inherits environment guard from InMemoryAdapter.
    """

    def __init__(self) -> None:
        """Initialize adapter - validates test environment."""
        super().__init__()
        self._instances: dict[str, MemoryIsolationState] = {}

    async def create(self, config: IsolationConfig) -> IsolationHandle:
        """Create in-memory isolation instance.

        Args:
            config: Isolation configuration

        Returns:
            IsolationHandle for subsequent operations
        """
        from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
            IsolationHandle,
        )

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
        timeout_seconds: int | None = None,  # noqa: ARG002
        working_directory: str | None = None,  # noqa: ARG002
        environment: dict[str, str] | None = None,  # noqa: ARG002
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
        from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
            ExecutionResult,
        )

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

    async def copy_to(
        self,
        handle: IsolationHandle,
        files: list[tuple[str, bytes]],
        base_path: str = "/workspace",  # noqa: ARG002
    ) -> None:
        """Copy files into the mock isolation.

        Stores files in instance state for later retrieval.

        Args:
            handle: Handle from create()
            files: List of (relative_path, content) tuples
            base_path: Ignored in mock
        """
        state = self._instances.get(handle.isolation_id)
        if state is None:
            return

        for rel_path, content in files:
            state.files[rel_path] = content

    async def copy_from(
        self,
        handle: IsolationHandle,
        patterns: list[str],  # noqa: ARG002
        base_path: str = "/workspace",  # noqa: ARG002
    ) -> list[tuple[str, bytes]]:
        """Copy files out of the mock isolation.

        Returns stored files.

        Args:
            handle: Handle from create()
            patterns: Ignored in mock (returns all files)
            base_path: Ignored in mock

        Returns:
            All stored files
        """
        state = self._instances.get(handle.isolation_id)
        if state is None:
            return []

        return list(state.files.items())

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
