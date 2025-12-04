"""Workspace protocol - interface for agent execution environments.

Workspaces provide isolated directories where agents execute tasks.
Each workspace:
- Has hooks from agentic-primitives pre-configured
- Can have context injected from previous phases
- Collects artifacts after execution
- Can be cleaned up automatically
"""

from __future__ import annotations

from abc import abstractmethod
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from contextlib import AbstractAsyncContextManager
    from pathlib import Path

    from aef_adapters.agents.agentic_types import Workspace, WorkspaceConfig


@runtime_checkable
class WorkspaceProtocol(Protocol):
    """Protocol for workspace implementations.

    Workspaces are used as async context managers:

        async with LocalWorkspace.create(config) as workspace:
            # workspace.path is ready with hooks configured
            await agent.execute(task, workspace, ...)
            # artifacts collected automatically on exit
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
