"""gVisor Docker workspace - isolated execution with user-space kernel.

gVisor provides strong isolation by intercepting syscalls and executing them
in a user-space kernel, preventing direct host kernel access.

Requirements:
- Docker with gVisor runtime installed (runsc)
- Docker daemon running

Configuration:
- Uses AEF_WORKSPACE_DOCKER_IMAGE for the container image
- Uses runsc runtime for gVisor isolation
- Applies resource limits from WorkspaceSecuritySettings

See ADR-021: Isolated Workspace Architecture
"""

from __future__ import annotations

import asyncio
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

from aef_adapters.workspaces.base import BaseIsolatedWorkspace
from aef_adapters.workspaces.types import IsolatedWorkspace, IsolatedWorkspaceConfig
from aef_shared.settings import IsolationBackend

if TYPE_CHECKING:
    from aef_shared.settings import WorkspaceSecuritySettings


class GVisorWorkspace(BaseIsolatedWorkspace):
    """Docker workspace using gVisor runtime for syscall interception.

    gVisor intercepts all syscalls and executes them in a user-space kernel,
    providing defense-in-depth against kernel exploits.

    Advantages:
    - Stronger isolation than native Docker (no direct kernel access)
    - Works on Linux and macOS (Docker Desktop includes runsc)
    - Compatible with existing Docker images

    Disadvantages:
    - Higher overhead than native Docker (~10-20%)
    - Some syscalls not fully supported
    - Requires runsc runtime installation

    Usage:
        async with GVisorWorkspace.create(config) as workspace:
            exit_code, stdout, stderr = await GVisorWorkspace.execute_command(
                workspace, ["python", "script.py"]
            )
    """

    isolation_backend: ClassVar[IsolationBackend] = IsolationBackend.GVISOR

    @classmethod
    def is_available(cls) -> bool:
        """Check if Docker and gVisor runtime are available.

        Returns:
            True if Docker is installed and runsc runtime is configured.
        """
        # Check Docker is available
        if shutil.which("docker") is None:
            return False

        # Check if runsc runtime is available
        # Note: On Docker Desktop for macOS, runsc might not be directly callable
        # but could be available as a Docker runtime
        return cls._check_docker_runtime_available()

    @classmethod
    def _check_docker_runtime_available(cls) -> bool:
        """Check if Docker has runsc runtime configured."""
        import subprocess

        try:
            # Check Docker info for runsc runtime
            result = subprocess.run(
                ["docker", "info", "--format", "{{json .Runtimes}}"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                runtimes_json = result.stdout.strip()
                # Check if runsc is in the runtimes
                return "runsc" in runtimes_json or "gvisor" in runtimes_json
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

        # Fallback: check if runsc binary exists
        return shutil.which("runsc") is not None

    @classmethod
    async def _create_isolation(
        cls,
        config: IsolatedWorkspaceConfig,
        security: WorkspaceSecuritySettings,
    ) -> IsolatedWorkspace:
        """Create a Docker container with gVisor runtime.

        Args:
            config: Workspace configuration
            security: Security settings to apply

        Returns:
            IsolatedWorkspace with container_id populated
        """
        from aef_shared.settings import get_settings

        settings = get_settings()
        workspace_settings = settings.workspace

        # Create local workspace directory
        if config.base_config.base_dir:
            workspace_dir = config.base_config.base_dir / config.session_id
        else:
            workspace_dir = Path(tempfile.mkdtemp(prefix=f"aef-gvisor-{config.session_id}-"))

        workspace_dir.mkdir(parents=True, exist_ok=True)

        # Generate unique container name
        container_name = f"aef-gvisor-{config.session_id}-{uuid.uuid4().hex[:8]}"

        # Build docker run command
        docker_cmd = cls._build_docker_command(
            container_name=container_name,
            workspace_dir=workspace_dir,
            image=workspace_settings.docker_image,
            runtime="runsc",  # gVisor runtime
            security=security,
            network=workspace_settings.docker_network,
        )

        # Start the container
        proc = await asyncio.create_subprocess_exec(
            *docker_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            error_msg = stderr.decode() if stderr else "Unknown error"
            raise RuntimeError(f"Failed to create gVisor container: {error_msg}")

        container_id = stdout.decode().strip()

        return IsolatedWorkspace(
            path=workspace_dir,
            config=config.base_config,
            isolation_backend=cls.isolation_backend,
            container_id=container_id,
            security=security,
        )

    @classmethod
    def _build_docker_command(
        cls,
        *,
        container_name: str,
        workspace_dir: Path,
        image: str,
        runtime: str,
        security: WorkspaceSecuritySettings,
        network: str,
    ) -> list[str]:
        """Build the docker run command with all security options.

        Args:
            container_name: Name for the container
            workspace_dir: Host path to mount as workspace
            image: Docker image to use
            runtime: Docker runtime (runsc for gVisor)
            security: Security settings to apply
            network: Docker network to use

        Returns:
            List of command arguments for docker run
        """
        cmd = [
            "docker",
            "run",
            "--detach",
            "--name",
            container_name,
            "--runtime",
            runtime,
            # Mount workspace directory
            "--mount",
            f"type=bind,source={workspace_dir},target=/workspace",
            # Working directory
            "--workdir",
            "/workspace",
        ]

        # Network isolation
        if not security.allow_network or network == "none":
            cmd.extend(["--network", "none"])
        else:
            cmd.extend(["--network", network])

        # Resource limits (use Docker format for memory, not Kubernetes format)
        cmd.extend(
            [
                "--memory",
                security.get_docker_memory(),
                "--cpus",
                str(security.max_cpu),
                "--pids-limit",
                str(security.max_pids),
            ]
        )

        # Read-only root filesystem
        if security.read_only_root:
            cmd.append("--read-only")
            # Add tmpfs for writable directories
            cmd.extend(
                [
                    "--tmpfs",
                    "/tmp:size=256m",
                    "--tmpfs",
                    "/var/tmp:size=64m",
                ]
            )

        # Security options
        cmd.extend(
            [
                # Drop all capabilities
                "--cap-drop=ALL",
                # No new privileges
                "--security-opt=no-new-privileges:true",
                # User namespace remapping (if supported)
                "--userns=host",  # Or use --user for UID mapping
            ]
        )

        # Environment variables
        cmd.extend(
            [
                "--env",
                "CLAUDE_PROJECT_DIR=/workspace",
                "--env",
                "HOME=/workspace",
                "--env",
                "WORKSPACE_DIR=/workspace",
            ]
        )

        # Inject API keys and tokens
        from aef_adapters.workspaces.env_injector import get_env_injector

        env_injector = get_env_injector()
        cmd.extend(env_injector.get_docker_env_args())

        # Image and command (sleep infinity to keep container running)
        cmd.extend([image, "sleep", "infinity"])

        return cmd

    @classmethod
    async def _destroy_isolation(cls, workspace: IsolatedWorkspace) -> None:
        """Stop and remove the Docker container.

        Args:
            workspace: The workspace to destroy
        """
        if not workspace.container_id:
            return

        # Stop the container
        stop_proc = await asyncio.create_subprocess_exec(
            "docker",
            "stop",
            "--time=5",  # 5 second grace period
            workspace.container_id,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await stop_proc.wait()

        # Remove the container
        rm_proc = await asyncio.create_subprocess_exec(
            "docker",
            "rm",
            "--force",
            workspace.container_id,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await rm_proc.wait()

    @classmethod
    async def execute_command(
        cls,
        workspace: IsolatedWorkspace,
        command: list[str],
        timeout: int | None = None,
        cwd: str | None = None,
    ) -> tuple[int, str, str]:
        """Execute a command inside the gVisor container.

        Args:
            workspace: The workspace to execute in
            command: Command and arguments to run
            timeout: Optional timeout in seconds
            cwd: Working directory (relative to workspace root)

        Returns:
            Tuple of (exit_code, stdout, stderr)
        """
        if not workspace.container_id:
            raise RuntimeError("Workspace container not running")

        # Build docker exec command
        exec_cmd = ["docker", "exec"]

        # Set working directory if specified
        if cwd:
            exec_cmd.extend(["--workdir", f"/workspace/{cwd}"])

        exec_cmd.append(workspace.container_id)
        exec_cmd.extend(command)

        # Execute with timeout
        try:
            proc = await asyncio.create_subprocess_exec(
                *exec_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            if timeout:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(),
                    timeout=timeout,
                )
            else:
                stdout, stderr = await proc.communicate()

            return (
                proc.returncode or 0,
                stdout.decode() if stdout else "",
                stderr.decode() if stderr else "",
            )

        except TimeoutError:
            # Kill the process if it times out
            proc.kill()
            await proc.wait()
            return (-1, "", f"Command timed out after {timeout} seconds")

    @classmethod
    async def health_check(cls, workspace: IsolatedWorkspace) -> bool:
        """Verify the gVisor container is healthy.

        Checks:
        - Container is running
        - Can execute commands inside
        - Workspace directory is accessible

        Args:
            workspace: The workspace to check

        Returns:
            True if healthy, False otherwise
        """
        if not workspace.container_id or not workspace.is_running:
            return False

        try:
            # Check container is running
            proc = await asyncio.create_subprocess_exec(
                "docker",
                "inspect",
                "--format",
                "{{.State.Running}}",
                workspace.container_id,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            stdout, _ = await proc.communicate()

            if proc.returncode != 0 or stdout.decode().strip() != "true":
                return False

            # Check we can execute commands
            exit_code, _, _ = await cls.execute_command(
                workspace,
                ["true"],
                timeout=5,
            )

            return exit_code == 0

        except Exception:
            return False

    @classmethod
    async def get_resource_usage(
        cls,
        workspace: IsolatedWorkspace,
    ) -> dict[str, int | float]:
        """Get current resource usage for the container.

        Args:
            workspace: The workspace to check

        Returns:
            Dict with memory_bytes, cpu_percent, pids
        """
        if not workspace.container_id:
            return {"memory_bytes": 0, "cpu_percent": 0.0, "pids": 0}

        try:
            proc = await asyncio.create_subprocess_exec(
                "docker",
                "stats",
                "--no-stream",
                "--format",
                "{{.MemUsage}}\t{{.CPUPerc}}\t{{.PIDs}}",
                workspace.container_id,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            stdout, _ = await proc.communicate()

            if proc.returncode != 0:
                return {"memory_bytes": 0, "cpu_percent": 0.0, "pids": 0}

            parts = stdout.decode().strip().split("\t")
            if len(parts) >= 3:
                mem_str = parts[0].split("/")[0].strip()  # e.g., "256MiB"
                cpu_str = parts[1].replace("%", "").strip()  # e.g., "0.50"
                pids_str = parts[2].strip()  # e.g., "5"

                # Parse memory (convert to bytes)
                mem_bytes = cls._parse_memory_string(mem_str)

                return {
                    "memory_bytes": mem_bytes,
                    "cpu_percent": float(cpu_str) if cpu_str else 0.0,
                    "pids": int(pids_str) if pids_str.isdigit() else 0,
                }

        except Exception:
            pass

        return {"memory_bytes": 0, "cpu_percent": 0.0, "pids": 0}

    @classmethod
    def _parse_memory_string(cls, mem_str: str) -> int:
        """Parse Docker memory string to bytes.

        Args:
            mem_str: Memory string like "256MiB", "1.5GiB", "100MB"

        Returns:
            Memory in bytes
        """
        mem_str = mem_str.strip().upper()

        # Extract number and unit
        for i, char in enumerate(mem_str):
            if not char.isdigit() and char != ".":
                number_part = mem_str[:i]
                unit_part = mem_str[i:]
                break
        else:
            return int(float(mem_str))

        try:
            value = float(number_part)
        except ValueError:
            return 0

        # Convert to bytes
        unit_multipliers = {
            "B": 1,
            "KB": 1024,
            "KIB": 1024,
            "MB": 1024**2,
            "MIB": 1024**2,
            "GB": 1024**3,
            "GIB": 1024**3,
            "TB": 1024**4,
            "TIB": 1024**4,
        }

        multiplier = unit_multipliers.get(unit_part, 1)
        return int(value * multiplier)
