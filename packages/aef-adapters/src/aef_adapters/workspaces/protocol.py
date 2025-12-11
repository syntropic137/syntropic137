"""Workspace protocol - interface for agent execution environments.

Workspaces provide isolated directories where agents execute tasks.
Each workspace:
- Has hooks from agentic-primitives pre-configured
- Can have context injected from previous phases
- Collects artifacts after execution
- Can be cleaned up automatically

For isolated workspaces (all production use), see IsolatedWorkspaceProtocol.
See ADR-021: Isolated Workspace Architecture
"""

from __future__ import annotations

from abc import abstractmethod
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from contextlib import AbstractAsyncContextManager
    from pathlib import Path

    from aef_adapters.agents.agentic_types import Workspace, WorkspaceConfig
    from aef_adapters.workspaces.types import (
        IsolatedWorkspace,
        IsolatedWorkspaceConfig,
    )
    from aef_shared.settings import IsolationBackend


@runtime_checkable
class WorkspaceProtocol(Protocol):
    """Protocol for workspace implementations.

    Workspaces are used as async context managers:

        async with LocalWorkspace.create(config) as workspace:
            # workspace.path is ready with hooks configured
            await agent.execute(task, workspace, ...)
            # artifacts collected automatically on exit

    Note: For production use with isolation, see IsolatedWorkspaceProtocol.
    """

    @classmethod
    @abstractmethod
    def create(cls, config: WorkspaceConfig) -> AbstractAsyncContextManager[Workspace]:
        """Create a workspace from configuration.

        This is an async context manager that:
        1. Sets up the workspace directory
        2. Configures hooks from agentic-primitives
        3. Yields the workspace for use
        4. Cleans up on exit (if configured)

        Args:
            config: Workspace configuration

        Yields:
            Configured Workspace ready for agent execution
        """
        ...

    @abstractmethod
    async def inject_context(
        self,
        workspace: Workspace,
        files: list[tuple[Path, bytes]],
        metadata: dict[str, object] | None = None,
    ) -> None:
        """Inject context files into the workspace.

        Used to provide artifacts from previous phases as context
        for the current agent execution.

        Args:
            workspace: The workspace to inject into
            files: List of (relative_path, content) tuples
            metadata: Optional metadata to write as context.json
        """
        ...

    @abstractmethod
    async def collect_artifacts(
        self,
        workspace: Workspace,
        output_patterns: list[str] | None = None,
    ) -> list[tuple[Path, bytes]]:
        """Collect artifacts from the workspace output directory.

        Args:
            workspace: The workspace to collect from
            output_patterns: Glob patterns to match (default: all files)

        Returns:
            List of (relative_path, content) tuples
        """
        ...


@runtime_checkable
class IsolatedWorkspaceProtocol(Protocol):
    """Protocol for isolated workspace implementations.

    All production workspaces are isolated. This protocol extends
    WorkspaceProtocol with isolation-specific requirements:
    - Backend availability checking
    - Security configuration
    - Health checking
    - Command execution inside isolation

    See ADR-021: Isolated Workspace Architecture

    Usage:

        async with GVisorWorkspace.create(config) as workspace:
            # workspace is isolated in a gVisor container
            exit_code, stdout, stderr = await GVisorWorkspace.execute_command(
                workspace, ["python", "script.py"]
            )
    """

    # Class attribute: which isolation backend this implements
    isolation_backend: IsolationBackend

    @classmethod
    @abstractmethod
    def is_available(cls) -> bool:
        """Check if this backend is available on the current platform.

        Should check for:
        - Required binaries (firecracker, docker, etc.)
        - Required kernel features (KVM, cgroups, etc.)
        - Required runtimes (gVisor runsc, Kata, etc.)

        Returns:
            True if this backend can be used, False otherwise.
        """
        ...

    @classmethod
    @abstractmethod
    def create(
        cls,
        config: IsolatedWorkspaceConfig,
    ) -> AbstractAsyncContextManager[IsolatedWorkspace]:
        """Create an isolated workspace from configuration.

        This is an async context manager that:
        1. Creates the isolation environment (container/VM/sandbox)
        2. Sets up hooks and configuration inside isolation
        3. Yields the IsolatedWorkspace for use
        4. Cleans up on exit

        Args:
            config: Isolated workspace configuration

        Yields:
            Configured IsolatedWorkspace ready for agent execution
        """
        ...

    @classmethod
    @abstractmethod
    async def inject_context(
        cls,
        workspace: IsolatedWorkspace,
        files: list[tuple[Path, bytes]],
        metadata: dict[str, object] | None = None,
    ) -> None:
        """Inject context files into the isolated workspace.

        Args:
            workspace: The isolated workspace to inject into
            files: List of (relative_path, content) tuples
            metadata: Optional metadata to write as context.json
        """
        ...

    @classmethod
    @abstractmethod
    async def collect_artifacts(
        cls,
        workspace: IsolatedWorkspace,
        output_patterns: list[str] | None = None,
    ) -> list[tuple[Path, bytes]]:
        """Collect artifacts from the isolated workspace output directory.

        Args:
            workspace: The isolated workspace to collect from
            output_patterns: Glob patterns to match (default: all files)

        Returns:
            List of (relative_path, content) tuples
        """
        ...

    @classmethod
    @abstractmethod
    async def health_check(cls, workspace: IsolatedWorkspace) -> bool:
        """Verify the isolation is working correctly.

        Should check that:
        - The isolation environment is running
        - The workspace is accessible
        - No escape conditions detected

        Args:
            workspace: The isolated workspace to check

        Returns:
            True if the workspace is healthy, False otherwise
        """
        ...

    @classmethod
    @abstractmethod
    async def execute_command(
        cls,
        workspace: IsolatedWorkspace,
        command: list[str],
        timeout: int | None = None,
        cwd: str | None = None,
    ) -> tuple[int, str, str]:
        """Execute a command inside the isolated workspace.

        Args:
            workspace: The isolated workspace to execute in
            command: Command and arguments to run
            timeout: Optional timeout in seconds
            cwd: Working directory (relative to workspace root)

        Returns:
            Tuple of (exit_code, stdout, stderr)
        """
        ...
