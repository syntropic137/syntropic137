"""Sidecar proxy manager for zero-trust token injection.

The SidecarManager handles lifecycle of Envoy sidecar proxy containers.
Each workspace gets its own sidecar that:

1. Intercepts outbound HTTP(S) requests
2. Injects authentication tokens (Claude, GitHub)
3. Enforces spend limits
4. Creates audit trail for all API calls

Architecture:
    ┌─────────────────────────────────────────────────────┐
    │  Workspace Pod/Container Group                       │
    │                                                      │
    │  ┌──────────────┐      ┌──────────────┐             │
    │  │    Agent     │ HTTP │   Sidecar    │ HTTPS → APIs│
    │  │  Container   │─────▶│    Proxy     │─────────────│
    │  │              │      │   (Envoy)    │             │
    │  └──────────────┘      └──────────────┘             │
    │                               │                      │
    │                        Token Vending                 │
    │                          Service                     │
    └─────────────────────────────────────────────────────┘

See ADR-022: Secure Token Architecture
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Default sidecar image
DEFAULT_SIDECAR_IMAGE = "aef-sidecar:latest"

# Default sidecar port
DEFAULT_SIDECAR_PORT = 8081


@dataclass
class SidecarConfig:
    """Configuration for a sidecar proxy instance."""

    # Execution context
    execution_id: str
    tenant_id: str | None = None

    # Sidecar image
    image: str = DEFAULT_SIDECAR_IMAGE

    # Network settings
    port: int = DEFAULT_SIDECAR_PORT
    network_name: str | None = None

    # Token vending service URL
    token_service_url: str = "http://host.docker.internal:8080"

    # Allowed hosts (comma-separated)
    allowed_hosts: str = "api.anthropic.com,api.github.com,raw.githubusercontent.com"

    # Resource limits
    memory_limit: str = "128m"
    cpu_limit: str = "0.25"


@dataclass
class SidecarInstance:
    """Running sidecar proxy instance."""

    container_id: str
    container_name: str
    config: SidecarConfig

    # Network info for linking workspace
    network_name: str
    proxy_url: str

    @property
    def http_proxy(self) -> str:
        """Get HTTP_PROXY value for workspace."""
        return self.proxy_url

    @property
    def https_proxy(self) -> str:
        """Get HTTPS_PROXY value for workspace."""
        return self.proxy_url


class SidecarManager:
    """Manages sidecar proxy container lifecycle.

    Creates and destroys sidecar containers for workspace isolation.
    Each workspace gets its own sidecar for security isolation.

    Example:
        manager = SidecarManager()

        config = SidecarConfig(
            execution_id="exec-123",
            tenant_id="tenant-abc",
        )

        async with manager.create(config) as sidecar:
            # sidecar.proxy_url = "http://sidecar-xxx:8081"
            # Use sidecar.http_proxy when creating workspace
            ...
    """

    def __init__(
        self,
        *,
        image: str = DEFAULT_SIDECAR_IMAGE,
        docker_host: str | None = None,
    ) -> None:
        """Initialize sidecar manager.

        Args:
            image: Default sidecar Docker image
            docker_host: Docker host URL (default: local socket)
        """
        self._default_image = image
        self._docker_host = docker_host or os.getenv("DOCKER_HOST")
        self._active_sidecars: dict[str, SidecarInstance] = {}
        self._lock = asyncio.Lock()

    async def create(self, config: SidecarConfig) -> SidecarInstance:
        """Create a new sidecar proxy container.

        Args:
            config: Sidecar configuration

        Returns:
            SidecarInstance with container info

        Raises:
            RuntimeError: If sidecar creation fails
        """
        container_name = f"aef-sidecar-{config.execution_id[:8]}-{uuid.uuid4().hex[:4]}"

        # Create a dedicated network for this sidecar+workspace pair
        network_name = config.network_name or f"aef-net-{config.execution_id[:8]}"

        # Build docker run command
        env_vars = [
            f"AEF_EXECUTION_ID={config.execution_id}",
            f"AEF_TOKEN_SERVICE_URL={config.token_service_url}",
            f"AEF_ALLOWED_HOSTS={config.allowed_hosts}",
        ]
        if config.tenant_id:
            env_vars.append(f"AEF_TENANT_ID={config.tenant_id}")

        try:
            # Create network if it doesn't exist
            await self._ensure_network(network_name)

            # Start sidecar container
            cmd = [
                "docker",
                "run",
                "-d",
                "--rm",
                f"--name={container_name}",
                f"--network={network_name}",
                f"--memory={config.memory_limit}",
                f"--cpus={config.cpu_limit}",
            ]

            # Add environment variables
            for env in env_vars:
                cmd.extend(["-e", env])

            # Add image
            cmd.append(config.image or self._default_image)

            logger.info(
                "Starting sidecar (name=%s, execution=%s)",
                container_name,
                config.execution_id,
            )

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()

            if proc.returncode != 0:
                raise RuntimeError(
                    f"Failed to start sidecar: {stderr.decode().strip()}"
                )

            container_id = stdout.decode().strip()

            # Wait for sidecar to be healthy
            await self._wait_for_healthy(container_name)

            # Build proxy URL (container name is DNS name on Docker network)
            proxy_url = f"http://{container_name}:{config.port}"

            instance = SidecarInstance(
                container_id=container_id,
                container_name=container_name,
                config=config,
                network_name=network_name,
                proxy_url=proxy_url,
            )

            async with self._lock:
                self._active_sidecars[container_name] = instance

            logger.info(
                "Sidecar started (name=%s, proxy=%s)",
                container_name,
                proxy_url,
            )

            return instance

        except Exception as e:
            logger.exception("Failed to create sidecar: %s", e)
            # Cleanup on failure
            await self._cleanup_container(container_name)
            await self._cleanup_network(network_name)
            raise

    async def destroy(self, sidecar: SidecarInstance) -> None:
        """Destroy a sidecar proxy container.

        Args:
            sidecar: The sidecar instance to destroy
        """
        container_name = sidecar.container_name

        logger.info("Destroying sidecar (name=%s)", container_name)

        async with self._lock:
            self._active_sidecars.pop(container_name, None)

        # Stop and remove container
        await self._cleanup_container(container_name)

        # Remove network (only if no other containers attached)
        await self._cleanup_network(sidecar.network_name)

    async def _ensure_network(self, network_name: str) -> None:
        """Ensure Docker network exists.

        Args:
            network_name: Network name to create
        """
        # Check if network exists
        check_cmd = ["docker", "network", "inspect", network_name]
        proc = await asyncio.create_subprocess_exec(
            *check_cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()

        if proc.returncode == 0:
            # Network already exists
            return

        # Create network
        create_cmd = ["docker", "network", "create", network_name]
        proc = await asyncio.create_subprocess_exec(
            *create_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()

        if proc.returncode != 0:
            raise RuntimeError(f"Failed to create network: {stderr.decode().strip()}")

        logger.debug("Created network: %s", network_name)

    async def _cleanup_container(self, container_name: str) -> None:
        """Stop and remove a container.

        Args:
            container_name: Container to cleanup
        """
        # Stop container (will also remove due to --rm flag)
        cmd = ["docker", "stop", container_name]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()

    async def _cleanup_network(self, network_name: str) -> None:
        """Remove a Docker network if empty.

        Args:
            network_name: Network to cleanup
        """
        cmd = ["docker", "network", "rm", network_name]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()

    async def _wait_for_healthy(
        self,
        container_name: str,
        timeout: float = 30.0,
        interval: float = 0.5,
    ) -> None:
        """Wait for sidecar to be healthy.

        Args:
            container_name: Container to check
            timeout: Maximum wait time in seconds
            interval: Poll interval in seconds

        Raises:
            TimeoutError: If sidecar doesn't become healthy
        """
        elapsed = 0.0

        while elapsed < timeout:
            # Check container health
            cmd = [
                "docker",
                "inspect",
                "--format",
                "{{.State.Health.Status}}",
                container_name,
            ]
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()

            status = stdout.decode().strip()
            if status == "healthy":
                return

            # Also accept "starting" with running container as success
            # (health check may not have completed yet)
            if status in ("starting", ""):
                # Check if container is at least running
                check_cmd = [
                    "docker",
                    "inspect",
                    "--format",
                    "{{.State.Running}}",
                    container_name,
                ]
                check_proc = await asyncio.create_subprocess_exec(
                    *check_cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                check_stdout, _ = await check_proc.communicate()
                if check_stdout.decode().strip() == "true":
                    # Container running, give it a short delay and consider ready
                    await asyncio.sleep(1.0)
                    return

            await asyncio.sleep(interval)
            elapsed += interval

        raise TimeoutError(f"Sidecar {container_name} did not become healthy")


# Singleton instance
_sidecar_manager: SidecarManager | None = None


def get_sidecar_manager() -> SidecarManager:
    """Get the singleton sidecar manager.

    Returns:
        SidecarManager instance
    """
    global _sidecar_manager
    if _sidecar_manager is None:
        _sidecar_manager = SidecarManager()
    return _sidecar_manager


def reset_sidecar_manager() -> None:
    """Reset the singleton sidecar manager (for testing)."""
    global _sidecar_manager
    _sidecar_manager = None
