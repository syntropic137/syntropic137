"""Workspace router - automatic backend selection and overflow management.

The WorkspaceRouter is the main entry point for creating isolated workspaces.
It automatically:
1. Selects the best available backend based on configuration
2. Falls back to alternatives if preferred backend unavailable
3. Overflows to cloud backends when local capacity is exceeded

Usage:
    from aef_adapters.workspaces import WorkspaceRouter

    router = WorkspaceRouter()
    async with router.create(config) as workspace:
        # workspace is isolated with the best available backend
        ...

See ADR-021: Isolated Workspace Architecture
"""

from __future__ import annotations

import asyncio
import contextlib
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

# These imports are needed at runtime for BACKEND_CLASSES mapping
from aef_adapters.workspaces.base import BaseIsolatedWorkspace  # noqa: TC001
from aef_adapters.workspaces.docker_hardened import HardenedDockerWorkspace
from aef_adapters.workspaces.e2b import E2BWorkspace
from aef_adapters.workspaces.env_injector import get_env_injector
from aef_adapters.workspaces.events import get_workspace_emitter
from aef_adapters.workspaces.firecracker import FirecrackerWorkspace
from aef_adapters.workspaces.git import get_git_injector
from aef_adapters.workspaces.gvisor import GVisorWorkspace
from aef_adapters.workspaces.types import (  # noqa: TC001
    IsolatedWorkspace,
    IsolatedWorkspaceConfig,
)
from aef_shared.settings import IsolationBackend

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from aef_adapters.artifacts.bundle import ArtifactBundle, ArtifactType


@dataclass
class RouterStats:
    """Statistics for workspace router operations."""

    total_created: int = 0
    active_count: int = 0
    overflow_count: int = 0
    failed_count: int = 0
    by_backend: dict[IsolationBackend, int] = field(default_factory=dict)


class WorkspaceRouter:
    """Routes workspace creation to the best available backend.

    The router handles:
    - Backend selection based on configuration and availability
    - Fallback to alternative backends
    - Overflow to cloud backends when local capacity exceeded
    - Tracking of active workspaces

    Example:
        router = WorkspaceRouter()

        # Create with automatic backend selection
        async with router.create(config) as workspace:
            await router.execute_command(workspace, ["python", "script.py"])

        # Force specific backend
        async with router.create(config, backend=IsolationBackend.FIRECRACKER) as ws:
            ...
    """

    # Priority order for backend fallback (strongest to weakest isolation)
    BACKEND_PRIORITY: ClassVar[list[IsolationBackend]] = [
        IsolationBackend.FIRECRACKER,
        IsolationBackend.KATA,
        IsolationBackend.GVISOR,
        IsolationBackend.DOCKER_HARDENED,
        IsolationBackend.CLOUD,
    ]

    # Map backends to their implementation classes
    BACKEND_CLASSES: ClassVar[dict[IsolationBackend, type[BaseIsolatedWorkspace]]] = {
        IsolationBackend.FIRECRACKER: FirecrackerWorkspace,
        IsolationBackend.GVISOR: GVisorWorkspace,
        IsolationBackend.DOCKER_HARDENED: HardenedDockerWorkspace,
        IsolationBackend.CLOUD: E2BWorkspace,
        # Note: KATA not implemented yet, falls through to next
    }

    def __init__(self) -> None:
        """Initialize the workspace router."""
        self._stats = RouterStats()
        self._active_workspaces: dict[
            str, tuple[IsolatedWorkspace, type[BaseIsolatedWorkspace]]
        ] = {}
        self._lock = asyncio.Lock()

    @property
    def stats(self) -> RouterStats:
        """Get router statistics."""
        return self._stats

    @property
    def active_count(self) -> int:
        """Get count of currently active workspaces."""
        return len(self._active_workspaces)

    def get_available_backends(self) -> list[IsolationBackend]:
        """Get list of currently available backends.

        Checks each backend's is_available() method.

        Returns:
            List of available IsolationBackend values
        """
        available = []
        for backend in self.BACKEND_PRIORITY:
            backend_class = self.BACKEND_CLASSES.get(backend)
            if backend_class and backend_class.is_available():
                available.append(backend)
        return available

    def get_best_backend(self) -> IsolationBackend:
        """Get the best available backend for this platform.

        Follows priority order and returns first available.

        Returns:
            Best available IsolationBackend

        Raises:
            RuntimeError: If no backend is available
        """
        available = self.get_available_backends()
        if not available:
            raise RuntimeError(
                "No isolation backend available. "
                "Install Docker, Firecracker, or configure E2B API key."
            )
        return available[0]

    def get_backend_class(self, backend: IsolationBackend) -> type[BaseIsolatedWorkspace]:
        """Get the implementation class for a backend.

        Args:
            backend: The isolation backend

        Returns:
            The workspace class for this backend

        Raises:
            ValueError: If backend not implemented
        """
        backend_class = self.BACKEND_CLASSES.get(backend)
        if backend_class is None:
            raise ValueError(f"Backend {backend} not implemented")
        return backend_class

    @asynccontextmanager
    async def create(
        self,
        config: IsolatedWorkspaceConfig,
        *,
        backend: IsolationBackend | None = None,
        allow_overflow: bool = True,
    ) -> AsyncIterator[IsolatedWorkspace]:
        """Create an isolated workspace with automatic backend selection.

        Args:
            config: Workspace configuration
            backend: Force specific backend (None = auto-select)
            allow_overflow: Allow overflow to cloud if local capacity exceeded

        Yields:
            IsolatedWorkspace ready for use

        Raises:
            RuntimeError: If no backend available or capacity exceeded
        """
        from aef_shared.settings import get_settings

        settings = get_settings()
        workspace_settings = settings.workspace

        # Determine which backend to use
        if backend is None:
            backend = config.isolation_backend or workspace_settings.isolation_backend

        # Check capacity before creating
        if self.active_count >= workspace_settings.max_concurrent:
            if allow_overflow and workspace_settings.enable_cloud_overflow:
                # Overflow to cloud
                backend = IsolationBackend.CLOUD
                self._stats.overflow_count += 1
            else:
                raise RuntimeError(
                    f"Maximum concurrent workspaces ({workspace_settings.max_concurrent}) exceeded"
                )

        # Get backend class
        backend_class = self._get_available_backend_class(backend)

        # Get event emitter
        emitter = get_workspace_emitter()

        # Generate workspace ID for tracking
        pre_workspace_id = f"ws-{uuid.uuid4().hex[:8]}"
        create_start = time.perf_counter()

        # Emit creating event
        await emitter.workspace_creating(config, pre_workspace_id)

        # Create the workspace
        try:
            async with backend_class.create(config) as workspace:
                # Track active workspace
                workspace_id = workspace.isolation_id or pre_workspace_id
                async with self._lock:
                    self._active_workspaces[workspace_id] = (workspace, backend_class)
                    self._stats.total_created += 1
                    self._stats.by_backend[backend] = self._stats.by_backend.get(backend, 0) + 1

                # Emit created event
                await emitter.workspace_created(workspace, config)

                # Inject git identity if configured
                await self._inject_git_identity(workspace, backend_class, config)

                # Inject API keys for LLM access
                await self._inject_api_keys(workspace, backend_class)

                # Setup logging directory
                await self._setup_logging(workspace, backend_class)

                commands_executed = 0
                try:
                    # Track command count in workspace metadata
                    workspace._command_count = 0  # type: ignore[attr-defined]
                    yield workspace
                    commands_executed = getattr(workspace, "_command_count", 0)
                finally:
                    # Emit destroying event (tracks destroy start time internally)
                    await emitter.workspace_destroying(workspace)

                    async with self._lock:
                        self._active_workspaces.pop(workspace_id, None)

                    # Calculate total lifetime
                    total_lifetime_ms = (time.perf_counter() - create_start) * 1000

                    # Emit destroyed event (after context manager cleanup)
                    await emitter.workspace_destroyed(
                        workspace,
                        total_lifetime_ms=total_lifetime_ms,
                        commands_executed=commands_executed,
                    )

        except Exception as e:
            self._stats.failed_count += 1
            await emitter.workspace_error(
                workspace_id=pre_workspace_id,
                session_id=config.base_config.session_id,
                operation="create",
                error=e,
                isolation_backend=backend.value if backend else None,
            )
            raise RuntimeError(f"Failed to create workspace with {backend}: {e}") from e

    async def _inject_git_identity(
        self,
        workspace: IsolatedWorkspace,
        backend_class: type[BaseIsolatedWorkspace],
        config: IsolatedWorkspaceConfig,
    ) -> None:
        """Inject git identity and credentials into workspace.

        Args:
            workspace: The workspace to configure
            backend_class: Backend class for command execution
            config: Workspace configuration
        """
        injector = get_git_injector()

        # Create executor function for the injector
        async def executor(
            ws: IsolatedWorkspace,
            cmd: list[str],
        ) -> tuple[int, str, str]:
            return await backend_class.execute_command(ws, cmd)

        # Get workflow override from config
        workflow_override = config.git_identity_override

        # Git identity not configured is OK for workspaces that don't need git
        with contextlib.suppress(ValueError):
            await injector.inject_identity(
                workspace,
                executor,
                workflow_override=workflow_override,
            )

    async def _inject_api_keys(
        self,
        workspace: IsolatedWorkspace,
        backend_class: type[BaseIsolatedWorkspace],
    ) -> None:
        """Inject API keys (Anthropic, OpenAI) into workspace.

        Args:
            workspace: The workspace to configure
            backend_class: Backend class for command execution
        """
        injector = get_env_injector()

        # Create executor function for the injector
        async def executor(
            ws: IsolatedWorkspace,
            cmd: list[str],
        ) -> tuple[int, str, str]:
            return await backend_class.execute_command(ws, cmd)

        # API keys not configured is OK for some workspaces
        with contextlib.suppress(ValueError):
            await injector.inject_api_keys(
                workspace,
                executor,
                require_anthropic=False,
            )

    async def _setup_logging(
        self,
        workspace: IsolatedWorkspace,
        backend_class: type[BaseIsolatedWorkspace],
    ) -> None:
        """Setup logging directory inside workspace.

        Args:
            workspace: The workspace to configure
            backend_class: Backend class for command execution
        """
        from aef_shared.settings import get_settings

        settings = get_settings()
        log_path = settings.container_logging.log_file_path

        # Create log directory
        log_dir = str(Path(log_path).parent)
        exit_code, _, _ = await backend_class.execute_command(
            workspace,
            ["mkdir", "-p", log_dir],
        )

        if exit_code == 0:
            # Initialize empty log file
            await backend_class.execute_command(
                workspace,
                ["touch", log_path],
            )

    def _get_available_backend_class(
        self, preferred: IsolationBackend
    ) -> type[BaseIsolatedWorkspace]:
        """Get an available backend class, with fallback.

        Args:
            preferred: Preferred backend to use

        Returns:
            Available backend class

        Raises:
            RuntimeError: If no backend available
        """
        # Try preferred backend first
        backend_class = self.BACKEND_CLASSES.get(preferred)
        if backend_class and backend_class.is_available():
            return backend_class

        # Fall back through priority order
        for backend in self.BACKEND_PRIORITY:
            backend_class = self.BACKEND_CLASSES.get(backend)
            if backend_class and backend_class.is_available():
                return backend_class

        raise RuntimeError("No isolation backend available")

    async def execute_command(
        self,
        workspace: IsolatedWorkspace,
        command: list[str],
        timeout: int | None = None,
        cwd: str | None = None,
    ) -> tuple[int, str, str]:
        """Execute a command in a workspace using the correct backend.

        Args:
            workspace: The workspace to execute in
            command: Command and arguments
            timeout: Optional timeout in seconds
            cwd: Working directory

        Returns:
            Tuple of (exit_code, stdout, stderr)
        """
        # Get the backend class for this workspace
        workspace_id = workspace.isolation_id or str(id(workspace))
        entry = self._active_workspaces.get(workspace_id)

        if entry is None:
            raise RuntimeError("Workspace not managed by this router")

        _, backend_class = entry

        # Execute and time command
        start_time = time.perf_counter()
        exit_code, stdout, stderr = await backend_class.execute_command(
            workspace, command, timeout, cwd
        )
        duration_ms = (time.perf_counter() - start_time) * 1000

        # Track command count
        if hasattr(workspace, "_command_count"):
            workspace._command_count += 1

        # Emit command executed event
        emitter = get_workspace_emitter()
        await emitter.workspace_command_executed(
            workspace,
            command,
            exit_code,
            duration_ms,
            stdout_lines=len(stdout.split("\n")) if stdout else 0,
            stderr_lines=len(stderr.split("\n")) if stderr else 0,
        )

        return exit_code, stdout, stderr

    async def health_check(self, workspace: IsolatedWorkspace) -> bool:
        """Check workspace health using the correct backend.

        Args:
            workspace: The workspace to check

        Returns:
            True if healthy, False otherwise
        """
        workspace_id = workspace.isolation_id or str(id(workspace))
        entry = self._active_workspaces.get(workspace_id)

        if entry is None:
            return False

        _, backend_class = entry
        return await backend_class.health_check(workspace)

    async def inject_context(
        self,
        workspace: IsolatedWorkspace,
        files: list[tuple[str, bytes]],
        metadata: dict[str, object] | None = None,
    ) -> None:
        """Inject context into a workspace.

        Args:
            workspace: The workspace
            files: List of (path, content) tuples
            metadata: Optional metadata dict
        """
        from pathlib import Path

        path_files = [(Path(p), content) for p, content in files]

        workspace_id = workspace.isolation_id or str(id(workspace))
        entry = self._active_workspaces.get(workspace_id)

        if entry is None:
            raise RuntimeError("Workspace not managed by this router")

        _, backend_class = entry
        await backend_class.inject_context(workspace, path_files, metadata)

    async def collect_artifacts(
        self,
        workspace: IsolatedWorkspace,
        patterns: list[str] | None = None,
    ) -> list[tuple[str, bytes]]:
        """Collect artifacts from a workspace.

        Args:
            workspace: The workspace
            patterns: Optional glob patterns

        Returns:
            List of (path, content) tuples
        """
        workspace_id = workspace.isolation_id or str(id(workspace))
        entry = self._active_workspaces.get(workspace_id)

        if entry is None:
            raise RuntimeError("Workspace not managed by this router")

        _, backend_class = entry
        artifacts = await backend_class.collect_artifacts(workspace, patterns)
        return [(str(p), content) for p, content in artifacts]

    async def collect_and_store_artifacts(
        self,
        workspace: IsolatedWorkspace,
        bundle_id: str,
        phase_id: str,
        *,
        patterns: list[str] | None = None,
        workflow_id: str | None = None,
        session_id: str | None = None,
        store_to_storage: bool = True,
    ) -> ArtifactBundle:
        """Collect artifacts from workspace and optionally store to object storage.

        Combines artifact collection with bundling and optional storage upload.
        This is the recommended way to collect outputs from a phase execution.

        Args:
            workspace: The workspace to collect from.
            bundle_id: Unique identifier for this bundle.
            phase_id: Phase that produced these artifacts.
            patterns: Optional glob patterns to filter files.
            workflow_id: Workflow ID for storage organization.
            session_id: Session ID for storage organization.
            store_to_storage: Whether to upload to object storage.

        Returns:
            ArtifactBundle containing all collected files.

        Example:
            async with router.create(config) as workspace:
                # ... agent execution ...

                bundle = await router.collect_and_store_artifacts(
                    workspace,
                    bundle_id="research-001",
                    phase_id="research",
                    workflow_id=workflow_id,
                )
                # bundle is now saved to object storage
        """
        from aef_adapters.artifacts.bundle import ArtifactBundle

        # Collect artifacts from workspace
        artifacts = await self.collect_artifacts(workspace, patterns)

        # Create bundle
        bundle = ArtifactBundle(
            bundle_id=bundle_id,
            phase_id=phase_id,
            session_id=session_id,
            workflow_id=workflow_id,
        )

        # Add each artifact to bundle
        for path_str, content in artifacts:
            path = Path(path_str)

            # Infer artifact type from extension
            artifact_type = self._infer_artifact_type(path)

            bundle.add_file(
                path=path,
                content=content,
                artifact_type=artifact_type,
            )

        # Store to object storage if configured
        if store_to_storage:
            from aef_adapters.object_storage import get_storage

            storage = await get_storage()
            await bundle.save_to_storage(storage)

            # Emit event for artifact upload
            emitter = get_workspace_emitter()
            await emitter.artifacts_stored(
                workspace=workspace,
                bundle_id=bundle_id,
                file_count=bundle.file_count,
                total_size_bytes=bundle.total_size_bytes,
                storage_prefix=bundle.get_storage_prefix(),
            )

        return bundle

    def _infer_artifact_type(self, path: Path) -> ArtifactType:
        """Infer artifact type from file extension.

        Args:
            path: File path to analyze.

        Returns:
            Inferred ArtifactType.
        """
        from aef_adapters.artifacts.bundle import ArtifactType

        ext = path.suffix.lower()
        name = path.stem.lower()

        # Match by extension
        type_map = {
            ".md": ArtifactType.MARKDOWN,
            ".json": ArtifactType.JSON,
            ".yaml": ArtifactType.YAML,
            ".yml": ArtifactType.YAML,
            ".py": ArtifactType.CODE,
            ".js": ArtifactType.CODE,
            ".ts": ArtifactType.CODE,
            ".txt": ArtifactType.TEXT,
        }

        if ext in type_map:
            return type_map[ext]

        # Match by name patterns
        if "readme" in name:
            return ArtifactType.README
        if "plan" in name:
            return ArtifactType.PLAN
        if "test" in name:
            return ArtifactType.TEST_RESULTS
        if "report" in name:
            return ArtifactType.ANALYSIS_REPORT

        return ArtifactType.OTHER


# Singleton router instance for convenience
_default_router: WorkspaceRouter | None = None


def get_workspace_router() -> WorkspaceRouter:
    """Get the default workspace router instance.

    Returns:
        Singleton WorkspaceRouter instance
    """
    global _default_router
    if _default_router is None:
        _default_router = WorkspaceRouter()
    return _default_router


def reset_workspace_router() -> None:
    """Reset the default workspace router (for testing)."""
    global _default_router
    _default_router = None
