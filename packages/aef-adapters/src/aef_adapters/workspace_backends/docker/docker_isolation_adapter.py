"""Docker isolation adapter - creates and manages Docker containers.

Implements IsolationBackendPort for Docker-based workspace isolation.

Features:
- Creates hardened Docker containers with security options
- Supports gVisor runtime (runsc) when available
- Falls back to native runc with max hardening
- Resource limits (memory, CPU, pids)
- Read-only root filesystem with writable /workspace and /tmp

See ADR-021: Isolated Workspace Architecture
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aef_domain.contexts.workspaces._shared.value_objects import (
        ExecutionResult,
        IsolationConfig,
        IsolationHandle,
    )

logger = logging.getLogger(__name__)

# Default workspace image - matches image built by `just workspace-build`
DEFAULT_WORKSPACE_IMAGE = "aef-workspace-claude:latest"

# Default network
DEFAULT_NETWORK = "aef-workspace-net"


@dataclass
class DockerContainerState:
    """Internal state for a Docker container."""

    container_id: str
    container_name: str
    workspace_dir: Path
    network_name: str
    config: IsolationConfig
    is_running: bool = True


class DockerIsolationAdapter:
    """Docker implementation of IsolationBackendPort.

    Creates hardened Docker containers for workspace isolation.

    Security hardening applied:
    - --cap-drop=ALL: Drop all Linux capabilities
    - --security-opt=no-new-privileges: Prevent privilege escalation
    - --read-only: Read-only root filesystem
    - --tmpfs /tmp: Writable temp directory
    - --pids-limit: Process limit
    - --memory/--cpus: Resource limits
    - Seccomp default profile

    Usage:
        adapter = DockerIsolationAdapter()
        handle = await adapter.create(config)
        result = await adapter.execute(handle, ["python", "script.py"])
        await adapter.destroy(handle)
    """

    def __init__(
        self,
        *,
        default_image: str = DEFAULT_WORKSPACE_IMAGE,
        default_network: str = DEFAULT_NETWORK,
        use_gvisor: bool | None = None,
    ) -> None:
        """Initialize Docker isolation adapter.

        Args:
            default_image: Default Docker image for workspaces
            default_network: Default Docker network
            use_gvisor: Force gVisor runtime (None = auto-detect)
        """
        self._default_image = default_image
        self._default_network = default_network
        self._use_gvisor = use_gvisor if use_gvisor is not None else self._detect_gvisor()
        self._containers: dict[str, DockerContainerState] = {}
        self._lock = asyncio.Lock()

    @staticmethod
    def _detect_gvisor() -> bool:
        """Detect if gVisor runtime is available."""
        import subprocess

        try:
            result = subprocess.run(
                ["docker", "info", "--format", "{{json .Runtimes}}"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                return "runsc" in result.stdout or "gvisor" in result.stdout
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
        return False

    @staticmethod
    def is_available() -> bool:
        """Check if Docker is available."""
        return shutil.which("docker") is not None

    async def create(self, config: IsolationConfig) -> IsolationHandle:
        """Create a Docker container for workspace isolation.

        Args:
            config: Isolation configuration

        Returns:
            IsolationHandle for subsequent operations

        Raises:
            RuntimeError: If container creation fails
        """
        from aef_domain.contexts.workspaces._shared.value_objects import IsolationHandle

        # Generate unique names
        short_id = uuid.uuid4().hex[:8]
        container_name = f"aef-ws-{config.execution_id[:8]}-{short_id}"
        network_name = self._default_network

        # Create workspace directory on host
        workspace_dir = Path(tempfile.mkdtemp(prefix=f"aef-workspace-{short_id}-"))

        # Ensure network exists
        await self._ensure_network(network_name)

        # Build docker run command
        docker_cmd = self._build_docker_command(
            container_name=container_name,
            workspace_dir=workspace_dir,
            network_name=network_name,
            config=config,
        )

        logger.info(
            "Creating Docker container (name=%s, execution=%s, gvisor=%s)",
            container_name,
            config.execution_id,
            self._use_gvisor,
        )

        try:
            # Start container
            proc = await asyncio.create_subprocess_exec(
                *docker_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()

            if proc.returncode != 0:
                error_msg = stderr.decode().strip() if stderr else "Unknown error"
                raise RuntimeError(f"Failed to create container: {error_msg}")

            container_id = stdout.decode().strip()

            # Wait for container to be running
            await self._wait_for_running(container_name)

            # Store state
            state = DockerContainerState(
                container_id=container_id,
                container_name=container_name,
                workspace_dir=workspace_dir,
                network_name=network_name,
                config=config,
            )

            async with self._lock:
                self._containers[container_id] = state

            logger.info(
                "Container created (id=%s, name=%s)",
                container_id[:12],
                container_name,
            )

            return IsolationHandle(
                isolation_id=container_id,
                isolation_type="docker" if not self._use_gvisor else "gvisor",
                proxy_url=None,  # Set by sidecar adapter
                workspace_path="/workspace",
                host_workspace_path=str(workspace_dir),  # Host path for local agents
            )

        except Exception as e:
            # Cleanup on failure
            logger.exception("Failed to create container: %s", e)
            await self._cleanup_container(container_name)
            shutil.rmtree(workspace_dir, ignore_errors=True)
            raise

    async def destroy(self, handle: IsolationHandle) -> None:
        """Destroy a Docker container.

        Args:
            handle: Handle from create()
        """
        async with self._lock:
            state = self._containers.pop(handle.isolation_id, None)

        if state is None:
            logger.warning("Container not found for destruction: %s", handle.isolation_id[:12])
            return

        logger.info("Destroying container (id=%s)", handle.isolation_id[:12])

        # Stop and remove container
        await self._cleanup_container(state.container_name)

        # Remove workspace directory
        if state.workspace_dir.exists():
            shutil.rmtree(state.workspace_dir, ignore_errors=True)

    async def execute(
        self,
        handle: IsolationHandle,
        command: list[str],
        *,
        timeout_seconds: int | None = None,
        working_directory: str | None = None,
        environment: dict[str, str] | None = None,
    ) -> ExecutionResult:
        """Execute command inside Docker container.

        Args:
            handle: Handle from create()
            command: Command to execute
            timeout_seconds: Max execution time
            working_directory: Working directory override
            environment: Additional environment variables

        Returns:
            ExecutionResult with exit code, stdout, stderr
        """
        import time

        from aef_domain.contexts.workspaces._shared.value_objects import ExecutionResult

        state = self._containers.get(handle.isolation_id)
        if state is None:
            return ExecutionResult(
                exit_code=1,
                success=False,
                duration_ms=0.0,
                stderr="Container not found",
            )

        # Build docker exec command
        exec_cmd = ["docker", "exec"]

        # Working directory
        if working_directory:
            exec_cmd.extend(["-w", working_directory])
        else:
            exec_cmd.extend(["-w", "/workspace"])

        # Environment variables
        if environment:
            for key, value in environment.items():
                exec_cmd.extend(["-e", f"{key}={value}"])

        # Container name and command
        exec_cmd.append(state.container_name)
        exec_cmd.extend(command)

        start_time = time.perf_counter()
        timed_out = False

        try:
            proc = await asyncio.create_subprocess_exec(
                *exec_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(),
                    timeout=timeout_seconds or 3600,  # Default 1 hour
                )
            except TimeoutError:
                proc.kill()
                await proc.wait()
                timed_out = True
                stdout, stderr = b"", b"Command timed out"

            duration_ms = (time.perf_counter() - start_time) * 1000

            stdout_str = stdout.decode() if stdout else ""
            stderr_str = stderr.decode() if stderr else ""

            exit_code = -1 if timed_out else (proc.returncode or 0)
            return ExecutionResult(
                exit_code=exit_code,
                success=exit_code == 0 and not timed_out,
                duration_ms=duration_ms,
                stdout=stdout_str,
                stderr=stderr_str,
                stdout_lines=stdout_str.count("\n") + (1 if stdout_str else 0),
                stderr_lines=stderr_str.count("\n") + (1 if stderr_str else 0),
                timed_out=timed_out,
            )

        except Exception as e:
            duration_ms = (time.perf_counter() - start_time) * 1000
            return ExecutionResult(
                exit_code=1,
                success=False,
                duration_ms=duration_ms,
                stderr=str(e),
            )

    async def health_check(self, handle: IsolationHandle) -> bool:
        """Check if container is healthy and running.

        Args:
            handle: Handle from create()

        Returns:
            True if container is running
        """
        state = self._containers.get(handle.isolation_id)
        if state is None or not state.is_running:
            return False

        # Check container is actually running
        try:
            proc = await asyncio.create_subprocess_exec(
                "docker",
                "inspect",
                "-f",
                "{{.State.Running}}",
                state.container_name,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()
            return stdout.decode().strip().lower() == "true"
        except Exception:
            return False

    async def copy_to(
        self,
        handle: IsolationHandle,
        files: list[tuple[str, bytes]],
        base_path: str = "/workspace",  # noqa: ARG002
    ) -> None:
        """Copy files into the container.

        Uses docker cp to copy files. First writes to temp dir, then copies in.

        Args:
            handle: Handle from create()
            files: List of (relative_path, content) tuples
            base_path: Base path inside container
        """
        state = self._containers.get(handle.isolation_id)
        if not state:
            raise RuntimeError(f"Container not found: {handle.isolation_id}")

        # Write files to workspace directory (which is mounted)
        for rel_path, content in files:
            file_path = state.workspace_dir / rel_path
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_bytes(content)

        logger.debug(
            "Copied %d files to container (id=%s)",
            len(files),
            handle.isolation_id[:12],
        )

    async def copy_from(
        self,
        handle: IsolationHandle,
        patterns: list[str],
        base_path: str = "/workspace",  # noqa: ARG002
    ) -> list[tuple[str, bytes]]:
        """Copy files out of the container.

        Reads from mounted workspace directory.

        Args:
            handle: Handle from create()
            patterns: Glob patterns (e.g., ["artifacts/**/*"])
            base_path: Base path inside container

        Returns:
            List of (relative_path, content) tuples
        """
        import fnmatch

        state = self._containers.get(handle.isolation_id)
        if not state:
            raise RuntimeError(f"Container not found: {handle.isolation_id}")

        results: list[tuple[str, bytes]] = []

        # Search workspace directory for matching files
        for pattern in patterns:
            # Handle patterns like "artifacts/**/*"
            search_base = state.workspace_dir
            if "/" in pattern:
                # Extract base directory from pattern
                parts = pattern.split("/")
                for part in parts:
                    if "*" in part:
                        break
                    search_base = search_base / part
                    pattern = "/".join(parts[parts.index(part) + 1 :])

            if not search_base.exists():
                continue

            # Walk and match
            for file_path in search_base.rglob("*"):
                if file_path.is_file():
                    rel_path = file_path.relative_to(state.workspace_dir)
                    # Check if matches any pattern
                    if fnmatch.fnmatch(str(rel_path), pattern) or fnmatch.fnmatch(
                        str(rel_path), f"**/{pattern}"
                    ):
                        try:
                            content = file_path.read_bytes()
                            results.append((str(rel_path), content))
                        except Exception as e:
                            logger.warning("Failed to read %s: %s", file_path, e)

        logger.debug(
            "Collected %d files from container (id=%s)",
            len(results),
            handle.isolation_id[:12],
        )
        return results

    def _build_docker_command(
        self,
        *,
        container_name: str,
        workspace_dir: Path,
        network_name: str,
        config: IsolationConfig,
    ) -> list[str]:
        """Build docker run command with security hardening.

        Args:
            container_name: Name for the container
            workspace_dir: Host path to mount
            network_name: Docker network
            config: Isolation configuration

        Returns:
            Docker command as list of strings
        """
        security = config.security_policy

        cmd = [
            "docker",
            "run",
            "-d",  # Detached
            f"--name={container_name}",
            f"--network={network_name}",
            # Security hardening
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            "--read-only",
            "--tmpfs=/tmp:rw,noexec,nosuid,size=256m",
            # Resource limits
            f"--memory={security.memory_limit_mb}m",
            f"--cpus={security.cpu_limit_cores}",
            "--pids-limit=256",
            # Workspace mount
            f"-v={workspace_dir}:/workspace:rw",
            # Working directory
            "-w=/workspace",
        ]

        # Use gVisor runtime if available
        if self._use_gvisor:
            cmd.append("--runtime=runsc")

        # Environment from config
        if config.environment:
            for key, value in config.environment.items():
                cmd.extend(["-e", f"{key}={value}"])

        # Labels
        cmd.extend(
            [
                f"--label=aef.execution_id={config.execution_id}",
                f"--label=aef.workspace_id={config.workspace_id}",
            ]
        )
        if config.workflow_id:
            cmd.append(f"--label=aef.workflow_id={config.workflow_id}")

        # Image
        cmd.append(config.image or self._default_image)

        # Keep container running with sleep
        cmd.extend(["sleep", "infinity"])

        return cmd

    async def _ensure_network(self, network_name: str) -> None:
        """Ensure Docker network exists."""
        proc = await asyncio.create_subprocess_exec(
            "docker",
            "network",
            "inspect",
            network_name,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()

        if proc.returncode != 0:
            # Create network
            proc = await asyncio.create_subprocess_exec(
                "docker",
                "network",
                "create",
                network_name,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await proc.wait()

    async def _wait_for_running(self, container_name: str, timeout: float = 30.0) -> None:
        """Wait for container to be in running state."""
        import time

        start = time.time()
        while time.time() - start < timeout:
            proc = await asyncio.create_subprocess_exec(
                "docker",
                "inspect",
                "-f",
                "{{.State.Running}}",
                container_name,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()
            if stdout.decode().strip().lower() == "true":
                return
            await asyncio.sleep(0.1)

        raise RuntimeError(f"Container {container_name} did not start within {timeout}s")

    async def _cleanup_container(self, container_name: str) -> None:
        """Stop and remove a container."""
        # Stop
        proc = await asyncio.create_subprocess_exec(
            "docker",
            "stop",
            "-t",
            "5",
            container_name,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()

        # Remove
        proc = await asyncio.create_subprocess_exec(
            "docker",
            "rm",
            "-f",
            container_name,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()
