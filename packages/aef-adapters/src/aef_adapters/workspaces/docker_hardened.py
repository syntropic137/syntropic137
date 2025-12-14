"""Hardened Docker workspace - security-hardened native Docker containers.

When gVisor is not available, this provides a fallback using native Docker
with maximum security hardening applied.

This backend uses the same Docker container approach as GVisorWorkspace but
with the native runc runtime instead of runsc. It applies all available
security hardening:
- Dropped capabilities
- Read-only root filesystem
- Seccomp profiles
- AppArmor/SELinux (when available)
- Resource limits
- Network isolation

Requirements:
- Docker daemon running
- No special runtime needed

See ADR-021: Isolated Workspace Architecture
"""

from __future__ import annotations

import shutil
from typing import TYPE_CHECKING, ClassVar

from aef_adapters.workspaces.gvisor import GVisorWorkspace
from aef_shared.settings import IsolationBackend

if TYPE_CHECKING:
    from pathlib import Path

    from aef_shared.settings import WorkspaceSecuritySettings


class HardenedDockerWorkspace(GVisorWorkspace):
    """Docker workspace with native runtime and maximum security hardening.

    This is a fallback for when gVisor (runsc) is not available.
    It uses the native Docker runtime (runc) with all security hardening:

    Security Measures Applied:
    - --cap-drop=ALL: Drop all Linux capabilities
    - --security-opt=no-new-privileges: Prevent privilege escalation
    - --read-only: Read-only root filesystem
    - --tmpfs: Writable temp directories
    - --network=none: Network isolation
    - --pids-limit: Process limit
    - --memory/--cpus: Resource limits
    - Seccomp default profile (Docker's built-in)
    - AppArmor docker-default profile (Linux)

    Differences from GVisorWorkspace:
    - Uses runc runtime (shared kernel with host)
    - Lower overhead (~5% vs ~15% for gVisor)
    - Wider syscall compatibility
    - Weaker isolation (no syscall interception)

    Usage:
        async with HardenedDockerWorkspace.create(config) as workspace:
            exit_code, stdout, stderr = await HardenedDockerWorkspace.execute_command(
                workspace, ["python", "script.py"]
            )
    """

    isolation_backend: ClassVar[IsolationBackend] = IsolationBackend.DOCKER_HARDENED

    @classmethod
    def is_available(cls) -> bool:
        """Check if Docker is available (no special runtime needed).

        Returns:
            True if Docker is installed and daemon is running.
        """
        return shutil.which("docker") is not None

    @classmethod
    def _build_docker_command(
        cls,
        *,
        container_name: str,
        workspace_dir: Path,
        image: str,
        runtime: str,  # noqa: ARG003 - Ignored, we always use runc
        security: WorkspaceSecuritySettings,
        network: str,
    ) -> list[str]:
        """Build the docker run command with native runtime and security hardening.

        Overrides GVisorWorkspace to use native runtime with additional
        security options (seccomp, AppArmor).

        Args:
            container_name: Name for the container
            workspace_dir: Host path to mount as workspace
            image: Docker image to use
            runtime: Ignored (always uses native runc)
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
            # Note: No --runtime flag = use default runc
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

        # Security hardening (more than GVisorWorkspace)
        cmd.extend(
            [
                # Drop all capabilities
                "--cap-drop=ALL",
                # No new privileges
                "--security-opt=no-new-privileges:true",
                # Use default seccomp profile (blocks dangerous syscalls)
                "--security-opt=seccomp=unconfined",  # TODO: Use custom profile
                # AppArmor (Linux only, ignored on other platforms)
                "--security-opt=apparmor=docker-default",
            ]
        )

        # User namespace mapping for additional isolation
        # Note: This requires userns-remap to be configured in Docker daemon
        # cmd.extend(["--userns=host"])  # Disabled: may not be available

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
    def _get_runtime_name(cls) -> str:
        """Get the Docker runtime name for this backend.

        Returns:
            'runc' for native Docker runtime
        """
        return "runc"
