"""Agentic workspace adapters - thin wrappers around agentic_isolation.

These adapters implement Syn137's domain ports by delegating to the
agentic_isolation library from agentic-primitives. This keeps Syn137
focused on orchestration and observability, not container management.

See ADR-021: Isolated Workspace Architecture
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from agentic_isolation import (
    SecurityConfig,
    WorkspaceDockerProvider,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

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
        import os

        self._default_image = default_image
        self._security = security or SecurityConfig.production()

        # Get paths from env or args
        container_dir = workspace_container_dir or os.environ.get(
            "SYN_WORKSPACE_CONTAINER_DIR", "/workspaces"
        )
        host_dir = workspace_host_dir or os.environ.get("SYN_WORKSPACE_HOST_DIR")

        self._container_base_dir = container_dir
        self._host_base_dir = host_dir  # May be None if same as container dir

        self._provider = WorkspaceDockerProvider(
            default_image=default_image,
            security=self._security,
            workspace_base_dir=container_dir,
            workspace_host_dir=host_dir,  # For Docker volume mounts
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
        ws_config = WorkspaceConfig(
            provider="docker",
            image=config.image or self._default_image,
            working_dir="/workspace",
            environment=config.environment or {},
            labels={
                "syn.execution_id": config.execution_id,
                "syn.workspace_id": config.workspace_id,
            },
            security=self._security,
        )

        # Create workspace via provider
        workspace_obj = await self._provider.create(ws_config)

        # Store for later operations
        self._workspaces[workspace_obj.id] = workspace_obj

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
        await self._provider.destroy(workspace)

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
            workspace,
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

        # Docker provider writes to mounted workspace_dir, paths are relative
        for path, content in files:
            relative_path = path.lstrip("/")
            await self._provider.write_file(workspace, relative_path, content)

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
        from pathlib import Path

        host_workspace = handle.host_workspace_path
        if not host_workspace:
            logger.warning(
                "copy_from: No host_workspace_path in handle (workspace=%s)",
                handle.isolation_id,
            )
            return []

        workspace_path = Path(host_workspace)
        logger.info(
            "copy_from: Checking path %s (exists=%s, workspace=%s)",
            workspace_path,
            workspace_path.exists(),
            handle.isolation_id,
        )

        if not workspace_path.exists():
            logger.warning(
                "copy_from: Workspace path does not exist (workspace=%s, path=%s)",
                handle.isolation_id,
                workspace_path,
            )
            return []

        # List what's actually in the workspace for debugging (guarded for performance)
        if logger.isEnabledFor(logging.DEBUG):
            try:
                all_files = list(workspace_path.rglob("*"))
                logger.debug(
                    "copy_from: Found %d total files in workspace: %s",
                    len(all_files),
                    [str(f.relative_to(workspace_path)) for f in all_files[:20]],
                )
            except Exception as e:
                logger.debug("copy_from: Failed to list files: %s", e)

        results: list[tuple[str, bytes]] = []
        seen_paths: set[str] = set()  # Avoid duplicates if patterns overlap

        # Use Path.glob() for each pattern - this properly handles **
        for pattern in patterns:
            # Clean the pattern for glob
            clean_pattern = pattern.lstrip("/")
            if clean_pattern.startswith("workspace/"):
                clean_pattern = clean_pattern[len("workspace/") :]

            logger.debug("copy_from: Globbing pattern: %s", clean_pattern)

            for file_path in workspace_path.glob(clean_pattern):
                if not file_path.is_file():
                    continue

                relative_path = str(file_path.relative_to(workspace_path))
                if relative_path in seen_paths:
                    continue
                seen_paths.add(relative_path)

                try:
                    content = file_path.read_bytes()
                    results.append((relative_path, content))
                    logger.info(
                        "copy_from: Collected file %s (%d bytes)",
                        relative_path,
                        len(content),
                    )
                except Exception as e:
                    logger.warning(
                        "copy_from: Failed to read file %s: %s",
                        relative_path,
                        e,
                    )

        logger.info(
            "copy_from: Collected %d files matching patterns %s (workspace=%s)",
            len(results),
            patterns,
            handle.isolation_id,
        )
        return results


class AgenticEventStreamAdapter:
    """Implements EventStreamPort using agentic_isolation streaming.

    This adapter provides real-time stdout streaming for observability.
    """

    def __init__(self) -> None:
        """Initialize the adapter."""
        self._provider: WorkspaceDockerProvider | None = None
        self._last_exit_code: int | None = None

    @property
    def last_exit_code(self) -> int | None:
        """Exit code from the most recent stream() call.

        Returns None if no stream has completed yet.
        """
        return self._last_exit_code

    def set_provider(self, provider: WorkspaceDockerProvider) -> None:
        """Set the provider for streaming.

        Called by AgenticIsolationAdapter to share the provider.
        """
        self._provider = provider

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

        Args:
            handle: Handle from isolation adapter
            command: Command to execute
            timeout_seconds: Max execution time
            working_directory: Working directory override
            environment: Additional environment variables

        Yields:
            Individual stdout lines as they are produced

        ARCHITECTURE NOTE — stderr=STDOUT is intentional (ADR-043):
        -----------------------------------------------------------------
        stderr=STDOUT merges any direct stderr from the claude CLI process into the
        stdout pipe so nothing is silently discarded (edge cases, internal errors).

        HOW GIT HOOK EVENTS ACTUALLY FLOW (important — not the obvious path):
        When Claude runs `git commit` via the Bash tool, the post-commit hook fires
        and emits JSONL to stderr. Claude Code captures Bash tool stderr as part of
        the tool output, then packages it inside a stream-json "user/tool_result"
        event. The JSONL arrives EMBEDDED inside tool_result content — NOT as a
        standalone raw line. WorkflowExecutionEngine scans each tool_result's full
        content string for embedded JSONL (see the tool_result branch in the loop).

        stderr=PIPE would silently discard any stderr escaping Claude Code's own
        packaging. Do not revert to PIPE or DEVNULL.

        IMPORTANT — TWO DOCKER EXEC PATHS EXIST. This file is the production path
        (used by the workspace service). agentic_isolation/providers/docker.py has
        the same fix but is only used in agentic_isolation contexts. Both must stay
        in sync — changing docker.py alone has no effect on the dashboard.
        """
        # Store timeout for use in the streaming loop
        stream_timeout = float(timeout_seconds) if timeout_seconds else None
        if self._provider is None:
            raise RuntimeError("Provider not set. Call set_provider first.")

        # Get the workspace from the isolation adapter
        # This is a bit awkward - in practice, we'd share state better
        # For now, we'll use docker exec directly

        container_name = f"agentic-ws-{handle.isolation_id.split('-')[1]}"

        import asyncio

        exec_cmd = ["docker", "exec", "-i"]

        if working_directory:
            exec_cmd.extend(["-w", working_directory])
        else:
            exec_cmd.extend(["-w", "/workspace"])

        if environment:
            for key, value in environment.items():
                exec_cmd.extend(["-e", f"{key}={value}"])

        exec_cmd.append(container_name)
        exec_cmd.extend(command)

        logger.debug(
            "Starting stream (container=%s, cmd=%s, timeout=%s)",
            container_name,
            command,
            stream_timeout,
        )

        import time

        start_time = time.monotonic()

        # stderr=STDOUT: merge stderr into stdout so git hook JSONL events
        # (emitted to stderr by post-commit/pre-push hooks) are read by the engine.
        # See docstring above for full architectural rationale.
        proc = await asyncio.create_subprocess_exec(
            *exec_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )

        try:
            while True:
                # Check overall timeout
                if stream_timeout is not None:
                    elapsed = time.monotonic() - start_time
                    if elapsed >= stream_timeout:
                        logger.warning("Stream timed out after %.1fs", elapsed)
                        break

                if proc.stdout is None:
                    break

                try:
                    line_bytes = await asyncio.wait_for(
                        proc.stdout.readline(),
                        timeout=1.0,
                    )
                except TimeoutError:
                    if proc.returncode is not None:
                        break
                    continue

                if not line_bytes:
                    break

                line = line_bytes.decode("utf-8", errors="replace").rstrip("\n\r")
                if line:
                    yield line

        finally:
            if proc.returncode is None:
                try:
                    proc.terminate()
                    await asyncio.wait_for(proc.wait(), timeout=5.0)
                except (TimeoutError, ProcessLookupError):
                    proc.kill()

            # Wait for process to fully exit if not already done
            if proc.returncode is None:
                await proc.wait()

            self._last_exit_code = proc.returncode
            if proc.returncode and proc.returncode != 0:
                logger.warning(
                    "Stream process exited with code %d (container=%s)",
                    proc.returncode,
                    container_name,
                )
