"""Agentic workspace adapters - thin wrappers around agentic_isolation.

These adapters implement Syn137's domain ports by delegating to the
agentic_isolation library from agentic-primitives. This keeps Syn137
focused on orchestration and observability, not container management.

See ADR-021: Isolated Workspace Architecture
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

from agentic_isolation import (
    SecurityConfig,
    WorkspaceDockerProvider,
)

from syn_shared.env_constants import (
    ENV_SYN_AGENT_NETWORK,
    ENV_SYN_WORKSPACE_CONTAINER_DIR,
    ENV_SYN_WORKSPACE_HOST_DIR,
)

from syn_adapters.workspace_backends.agentic.adapter_copy import (
    copy_from_workspace,
    copy_to_workspace,
)

if TYPE_CHECKING:
    from agentic_isolation import AgenticWorkspace

    from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
        ExecutionResult,
        IsolationConfig,
        IsolationHandle,
    )

logger = logging.getLogger(__name__)


class AgenticIsolationAdapter:
    """Implements IsolationBackendPort using agentic_isolation.

    This adapter delegates container lifecycle management to the
    WorkspaceDockerProvider from agentic-primitives.

    Usage:
        adapter = AgenticIsolationAdapter()
        handle = await adapter.create(config)
        result = await adapter.execute(handle, ["python", "script.py"])
        await adapter.destroy(handle)
    """

    def __init__(
        self,
        *,
        default_image: str = "agentic-workspace-claude-cli:latest",
        security: SecurityConfig | None = None,
        workspace_container_dir: str | None = None,
        workspace_host_dir: str | None = None,
    ) -> None:
        """Initialize the adapter.

        Args:
            default_image: Default Docker image for workspaces
            security: Security configuration (defaults to production)
            workspace_container_dir: Path inside orchestrator container (for file I/O)
            workspace_host_dir: Path on Docker host (for volume mounts)

        When running inside a container, both paths are needed:
        - container_dir: where this process writes files (/workspaces)
        - host_dir: what Docker uses for -v mount (host absolute path)

        Uses env vars SYN_WORKSPACE_CONTAINER_DIR and SYN_WORKSPACE_HOST_DIR if not set.
        """

        self._default_image = default_image
        self._security = security or SecurityConfig.production()

        # Get paths from env or args
        container_dir = workspace_container_dir or os.environ.get(
            ENV_SYN_WORKSPACE_CONTAINER_DIR, "/workspaces"
        )
        host_dir = workspace_host_dir or os.environ.get(ENV_SYN_WORKSPACE_HOST_DIR)

        self._container_base_dir = container_dir
        self._host_base_dir = host_dir  # May be None if same as container dir

        # ISS-43: Use agent-net so containers can reach the shared Envoy proxy
        # but cannot reach the internet directly.
        agent_network = os.environ.get(ENV_SYN_AGENT_NETWORK, "agent-net")

        self._provider = WorkspaceDockerProvider(
            default_image=default_image,
            security=self._security,
            workspace_base_dir=container_dir,
            workspace_host_dir=host_dir,  # For Docker volume mounts
            default_network=agent_network,
        )
        self._workspaces: dict[str, AgenticWorkspace] = {}

    @staticmethod
    def is_available() -> bool:
        """Check if Docker is available."""
        return WorkspaceDockerProvider.is_available()

    async def create(self, config: IsolationConfig) -> IsolationHandle:
        """Create an isolated workspace container.

        Args:
            config: Isolation configuration from Syn137 domain

        Returns:
            IsolationHandle for subsequent operations
        """
        from agentic_isolation import WorkspaceConfig

        from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
            IsolationHandle,
        )

        # Map Syn137 config to agentic_isolation config
        # ISS-43: Network is set on the provider (default_network in __init__),
        # not on WorkspaceConfig. Containers join agent-net to reach the shared
        # Envoy proxy but cannot reach the internet directly.
        ws_config = WorkspaceConfig(
            provider="docker",
            image=config.image or self._default_image,
            working_dir="/workspace",
            environment=dict(config.environment) if config.environment else {},
            labels={
                "syn.execution_id": config.execution_id,
                "syn.workspace_id": config.workspace_id,
            },
            security=self._security,
        )

        # Create workspace via provider
        workspace_obj = await self._provider.create(ws_config)

        # Store for later operations
        self._workspaces[workspace_obj.id] = workspace_obj  # type: ignore[arg-type]  # Workspace vs AgenticWorkspace adapter boundary

        logger.info(
            "Created workspace (id=%s, execution=%s)",
            workspace_obj.id,
            config.execution_id,
        )

        return IsolationHandle(
            isolation_id=workspace_obj.id,
            isolation_type="docker",
            proxy_url=None,
            workspace_path="/workspace",
            host_workspace_path=workspace_obj.metadata.get("workspace_dir", ""),
        )

    async def destroy(self, handle: IsolationHandle) -> None:
        """Destroy an isolated workspace.

        Args:
            handle: Handle from create()
        """
        workspace = self._workspaces.pop(handle.isolation_id, None)
        if workspace is None:
            logger.warning("Workspace not found: %s", handle.isolation_id)
            return

        logger.info("Destroying workspace (id=%s)", handle.isolation_id)
        await self._provider.destroy(workspace)  # type: ignore[arg-type]  # Workspace vs AgenticWorkspace adapter boundary

    async def execute(
        self,
        handle: IsolationHandle,
        command: list[str],
        *,
        timeout_seconds: int | None = None,
        working_directory: str | None = None,
        environment: dict[str, str] | None = None,
    ) -> ExecutionResult:
        """Execute command in workspace.

        Args:
            handle: Handle from create()
            command: Command to execute
            timeout_seconds: Max execution time
            working_directory: Working directory override
            environment: Additional environment variables

        Returns:
            ExecutionResult with exit code, stdout, stderr
        """
        from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
            ExecutionResult,
        )

        workspace = self._workspaces.get(handle.isolation_id)
        if workspace is None:
            return ExecutionResult(
                exit_code=1,
                success=False,
                duration_ms=0.0,
                stderr="Workspace not found",
            )

        # Join command list into shell command
        cmd_str = " ".join(command)

        result = await self._provider.execute(
            workspace,  # type: ignore[arg-type]  # Workspace vs AgenticWorkspace adapter boundary
            cmd_str,
            timeout=float(timeout_seconds) if timeout_seconds else None,
            cwd=working_directory,
            env=environment,
        )

        return ExecutionResult(
            exit_code=result.exit_code,
            success=result.success,
            duration_ms=result.duration_ms,
            stdout=result.stdout,
            stderr=result.stderr,
            timed_out=result.timed_out,
        )

    async def health_check(self, handle: IsolationHandle) -> bool:
        """Check if workspace is healthy.

        Args:
            handle: Handle from create()

        Returns:
            True if workspace is running
        """
        return handle.isolation_id in self._workspaces

    async def copy_to(
        self,
        handle: IsolationHandle,
        files: list[tuple[str, bytes]],
        base_path: str = "/workspace",  # noqa: ARG002 - interface param
    ) -> None:
        """Copy files into workspace.

        Args:
            handle: Handle from create()
            files: List of (path, content) tuples
            base_path: Base path (interface param, docker uses mounted volume)
        """
        workspace = self._workspaces.get(handle.isolation_id)
        if workspace is None:
            raise RuntimeError(f"Workspace not found: {handle.isolation_id}")

        await copy_to_workspace(self._provider, workspace, files)

    async def copy_from(
        self,
        handle: IsolationHandle,
        patterns: list[str],
        base_path: str = "/workspace",  # noqa: ARG002 - used for container path mapping
    ) -> list[tuple[str, bytes]]:
        """Copy files from workspace via mounted volume.

        The Docker provider mounts the workspace directory, so files created
        inside the container are accessible on the host at host_workspace_path.

        Args:
            handle: Handle from create()
            patterns: Glob patterns to match (e.g., ["artifacts/output/**/*"])
            base_path: Base path inside container (not used - we read from host mount)

        Returns:
            List of (relative_path, content) tuples for matching files
        """
        return await copy_from_workspace(handle, patterns)
