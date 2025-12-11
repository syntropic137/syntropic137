"""Network allowlist enforcement for isolated workspaces.

This module provides network control for agent containers:
- Egress proxy management (mitmproxy-based)
- Allowlist configuration
- Proxy environment injection

See ADR-021: Isolated Workspace Architecture - Network Allowlist

Usage:
    from aef_adapters.workspaces.network import EgressProxy, NetworkConfig

    # Start the proxy
    proxy = EgressProxy()
    await proxy.start()

    # Configure container to use proxy
    env_vars = proxy.get_proxy_env_vars()
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, ClassVar

if TYPE_CHECKING:
    from aef_adapters.workspaces.types import IsolatedWorkspace

logger = logging.getLogger(__name__)


# Default allowed hosts for agent operations
DEFAULT_ALLOWED_HOSTS: list[str] = [
    # LLM APIs
    "api.anthropic.com",
    "api.openai.com",
    # GitHub (for code operations)
    "github.com",
    "api.github.com",
    "raw.githubusercontent.com",
    # Python packages
    "pypi.org",
    "files.pythonhosted.org",
    # npm packages (for JS/TS projects)
    "registry.npmjs.org",
]


@dataclass
class NetworkConfig:
    """Network configuration for a workspace.

    Attributes:
        allow_network: Whether network access is allowed
        allowed_hosts: List of allowed hostnames
        use_proxy: Whether to route through egress proxy
        proxy_host: Egress proxy hostname
        proxy_port: Egress proxy port
    """

    allow_network: bool = True
    allowed_hosts: list[str] = field(default_factory=lambda: DEFAULT_ALLOWED_HOSTS.copy())
    use_proxy: bool = True
    proxy_host: str = "host.docker.internal"  # Access host from container
    proxy_port: int = 8080

    @classmethod
    def from_settings(cls) -> NetworkConfig:
        """Create config from settings."""
        from aef_shared.settings import get_settings

        settings = get_settings()
        security = settings.workspace_security

        return cls(
            allow_network=security.allow_network,
            allowed_hosts=security.get_allowed_hosts_list() or DEFAULT_ALLOWED_HOSTS.copy(),
            use_proxy=security.allow_network,  # Use proxy when network is allowed
        )

    def get_proxy_url(self) -> str:
        """Get the proxy URL for container configuration."""
        return f"http://{self.proxy_host}:{self.proxy_port}"

    def get_env_vars(self) -> dict[str, str]:
        """Get environment variables for proxy configuration.

        Returns:
            Dict of environment variables to set in container
        """
        if not self.allow_network or not self.use_proxy:
            return {}

        proxy_url = self.get_proxy_url()
        return {
            "HTTP_PROXY": proxy_url,
            "HTTPS_PROXY": proxy_url,
            "http_proxy": proxy_url,
            "https_proxy": proxy_url,
            # Don't proxy localhost
            "NO_PROXY": "localhost,127.0.0.1",
            "no_proxy": "localhost,127.0.0.1",
        }


class EgressProxy:
    """Manages the egress proxy container.

    The egress proxy runs as a Docker container and enforces
    network allowlisting for agent containers.

    Usage:
        proxy = EgressProxy()
        await proxy.start()
        # ... run agent containers ...
        await proxy.stop()
    """

    CONTAINER_NAME: ClassVar[str] = "aef-egress-proxy"
    IMAGE_NAME: ClassVar[str] = "aef-egress-proxy:latest"
    DEFAULT_PORT: ClassVar[int] = 8080

    def __init__(
        self,
        allowed_hosts: list[str] | None = None,
        port: int = DEFAULT_PORT,
    ) -> None:
        """Initialize the egress proxy.

        Args:
            allowed_hosts: List of allowed hostnames
            port: Port to expose the proxy on
        """
        self.allowed_hosts = allowed_hosts or DEFAULT_ALLOWED_HOSTS.copy()
        self.port = port
        self._container_id: str | None = None

    @property
    def is_running(self) -> bool:
        """Check if proxy container is running."""
        return self._container_id is not None

    async def start(self) -> bool:
        """Start the egress proxy container.

        Returns:
            True if started successfully
        """
        # Check if already running
        if await self._is_container_running():
            logger.info("Egress proxy already running")
            return True

        # Build the allowed hosts string
        hosts_str = ",".join(self.allowed_hosts)

        # Start the container
        cmd = [
            "docker",
            "run",
            "-d",
            "--name",
            self.CONTAINER_NAME,
            "-p",
            f"{self.port}:8080",
            "-e",
            f"ALLOWED_HOSTS={hosts_str}",
            "--restart",
            "unless-stopped",
            self.IMAGE_NAME,
        ]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()

            if proc.returncode == 0:
                self._container_id = stdout.decode().strip()[:12]
                logger.info(f"Egress proxy started: {self._container_id}")
                return True
            else:
                logger.error(f"Failed to start egress proxy: {stderr.decode()}")
                return False

        except Exception as e:
            logger.error(f"Error starting egress proxy: {e}")
            return False

    async def stop(self) -> bool:
        """Stop the egress proxy container.

        Returns:
            True if stopped successfully
        """
        cmd = ["docker", "rm", "-f", self.CONTAINER_NAME]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()

            self._container_id = None
            logger.info("Egress proxy stopped")
            return True

        except Exception as e:
            logger.error(f"Error stopping egress proxy: {e}")
            return False

    async def _is_container_running(self) -> bool:
        """Check if the proxy container is already running."""
        cmd = ["docker", "ps", "-q", "-f", f"name={self.CONTAINER_NAME}"]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()

            if stdout.decode().strip():
                self._container_id = stdout.decode().strip()[:12]
                return True
            return False

        except Exception:
            return False

    async def update_allowlist(self, hosts: list[str]) -> bool:
        """Update the allowlist (requires restart).

        Args:
            hosts: New list of allowed hosts

        Returns:
            True if updated successfully
        """
        self.allowed_hosts = hosts
        await self.stop()
        return await self.start()

    def get_docker_network_args(self) -> list[str]:
        """Get Docker arguments to route through proxy.

        Returns:
            List of Docker CLI arguments
        """
        if not self.is_running:
            return []

        config = NetworkConfig(
            allow_network=True,
            allowed_hosts=self.allowed_hosts,
            use_proxy=True,
            proxy_port=self.port,
        )

        args = []
        for key, value in config.get_env_vars().items():
            args.extend(["--env", f"{key}={value}"])

        return args


async def inject_proxy_config(
    workspace: IsolatedWorkspace,
    executor: callable,
    config: NetworkConfig,
) -> bool:
    """Inject proxy configuration into a workspace.

    Sets up environment variables for HTTP/HTTPS proxy.

    Args:
        workspace: The isolated workspace
        executor: Command executor function
        config: Network configuration

    Returns:
        True if configured successfully
    """
    if not config.allow_network or not config.use_proxy:
        return True

    env_vars = config.get_env_vars()
    if not env_vars:
        return True

    # Write to .bashrc/.profile for persistence
    export_lines = [f"export {k}='{v}'" for k, v in env_vars.items()]
    script = "\n".join(export_lines)

    write_cmd = [
        "sh",
        "-c",
        f'echo "{script}" >> ~/.bashrc && echo "{script}" >> ~/.profile',
    ]

    exit_code, _, stderr = await executor(workspace, write_cmd)
    if exit_code != 0:
        logger.error(f"Failed to inject proxy config: {stderr}")
        return False

    logger.info("Proxy configuration injected")
    return True


# Singleton proxy instance
_egress_proxy: EgressProxy | None = None


def get_egress_proxy() -> EgressProxy:
    """Get the default egress proxy instance."""
    global _egress_proxy
    if _egress_proxy is None:
        _egress_proxy = EgressProxy()
    return _egress_proxy


async def ensure_proxy_running(allowed_hosts: list[str] | None = None) -> EgressProxy:
    """Ensure the egress proxy is running.

    Args:
        allowed_hosts: Optional list of allowed hosts

    Returns:
        Running EgressProxy instance
    """
    proxy = get_egress_proxy()
    if allowed_hosts:
        proxy.allowed_hosts = allowed_hosts
    await proxy.start()
    return proxy
