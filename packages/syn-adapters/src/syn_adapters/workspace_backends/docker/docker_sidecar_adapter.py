"""Docker sidecar adapter - manages Envoy proxy containers.

Implements SidecarPort for Docker-based sidecar proxy management.

The sidecar proxy:
1. Intercepts outbound HTTP(S) requests from workspace
2. Injects authentication tokens (via ext_authz filter)
3. Enforces egress allowlist
4. Creates audit trail for API calls

Architecture:
    ┌─────────────────────────────────────────────────────┐
    │  Docker Network (syn-workspace-net)                  │
    │                                                      │
    │  ┌──────────────┐      ┌──────────────┐             │
    │  │  Workspace   │ HTTP │   Sidecar    │ HTTPS → APIs│
    │  │  Container   │─────▶│  (Envoy)     │─────────────│
    │  │              │      │              │             │
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
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
        IsolationHandle,
        SidecarConfig,
        SidecarHandle,
        TokenType,
    )

from syn_adapters.workspace_backends.docker.docker_container_ops import (
    cleanup_container,
    get_container_network,
    wait_for_healthy,
)

logger = logging.getLogger(__name__)

# Default sidecar image
DEFAULT_SIDECAR_IMAGE = "syn-sidecar-proxy:latest"

# Default sidecar port
DEFAULT_SIDECAR_PORT = 8080


@dataclass
class DockerSidecarState:
    """Internal state for a Docker sidecar container."""

    container_id: str
    container_name: str
    proxy_url: str
    network_name: str
    config: SidecarConfig
    started_at: datetime


class DockerSidecarAdapter:
    """Docker implementation of SidecarPort.

    Manages Envoy sidecar proxy containers for token injection and egress filtering.

    The sidecar is connected to the same Docker network as the workspace,
    allowing the workspace to route HTTP traffic through the proxy.

    Usage:
        sidecar_adapter = DockerSidecarAdapter()
        sidecar_handle = await sidecar_adapter.start(config, isolation_handle)

        # Configure tokens for injection
        await sidecar_adapter.configure_tokens(
            sidecar_handle,
            {TokenType.ANTHROPIC: "sk-ant-xxx"},
            ttl_seconds=300,
        )

        # Later: stop sidecar
        await sidecar_adapter.stop(sidecar_handle)
    """

    def __init__(
        self,
        *,
        default_image: str = DEFAULT_SIDECAR_IMAGE,
        token_service_url: str = "http://host.docker.internal:8080",
    ) -> None:
        """Initialize sidecar adapter.

        Args:
            default_image: Default sidecar Docker image
            token_service_url: URL of Token Vending Service
        """
        self._default_image = default_image
        self._token_service_url = token_service_url
        self._sidecars: dict[str, DockerSidecarState] = {}
        self._lock = asyncio.Lock()

    def _build_sidecar_docker_cmd(
        self,
        config: SidecarConfig,
        container_name: str,
        network_name: str,
    ) -> list[str]:
        """Build the docker run command for a sidecar container.

        Args:
            config: Sidecar configuration
            container_name: Name for the container
            network_name: Docker network to attach to

        Returns:
            Command arguments list for docker run.
        """
        env_vars = [
            f"SYN_WORKSPACE_ID={config.workspace_id}",
            f"SYN_TOKEN_SERVICE_URL={self._token_service_url}",
            f"SYN_ALLOWED_HOSTS={','.join(config.allowed_hosts)}",
            f"SYN_LISTEN_PORT={config.listen_port}",
        ]

        docker_cmd = [
            "docker",
            "run",
            "-d",
            "--rm",
            f"--name={container_name}",
            f"--network={network_name}",
            "--memory=128m",
            "--cpus=0.25",
        ]

        for env in env_vars:
            docker_cmd.extend(["-e", env])

        docker_cmd.extend(
            [
                f"--label=syn.workspace_id={config.workspace_id}",
                "--label=syn.component=sidecar",
            ]
        )

        docker_cmd.append(config.proxy_image or self._default_image)
        return docker_cmd

    async def _run_sidecar_container(self, docker_cmd: list[str]) -> str:
        """Execute docker run and return the container ID.

        Args:
            docker_cmd: Full docker run command arguments

        Returns:
            Container ID string.

        Raises:
            RuntimeError: If the docker run command fails.
        """
        proc = await asyncio.create_subprocess_exec(
            *docker_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            error_msg = stderr.decode().strip() if stderr else "Unknown error"
            raise RuntimeError(f"Failed to start sidecar: {error_msg}")

        return stdout.decode().strip()

    async def start(
        self,
        config: SidecarConfig,
        isolation_handle: IsolationHandle,
    ) -> SidecarHandle:
        """Start sidecar proxy container.

        Creates a sidecar container on the same Docker network as the workspace.

        Args:
            config: Sidecar configuration
            isolation_handle: Handle to the workspace container

        Returns:
            SidecarHandle for managing the sidecar

        Raises:
            RuntimeError: If sidecar creation fails
        """
        from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
            SidecarHandle,
        )

        short_id = uuid.uuid4().hex[:8]
        container_name = f"syn-sidecar-{config.workspace_id[:8]}-{short_id}"
        network_name = await get_container_network(isolation_handle.isolation_id)

        docker_cmd = self._build_sidecar_docker_cmd(config, container_name, network_name)

        logger.info(
            "Starting sidecar (name=%s, workspace=%s)",
            container_name,
            config.workspace_id,
        )

        try:
            container_id = await self._run_sidecar_container(docker_cmd)
            await wait_for_healthy(container_name, timeout=30.0)

            proxy_url = f"http://{container_name}:{config.listen_port}"
            state = DockerSidecarState(
                container_id=container_id,
                container_name=container_name,
                proxy_url=proxy_url,
                network_name=network_name,
                config=config,
                started_at=datetime.now(UTC),
            )

            async with self._lock:
                self._sidecars[container_id] = state

            logger.info("Sidecar started (id=%s, proxy=%s)", container_id[:12], proxy_url)

            return SidecarHandle(
                sidecar_id=container_id,
                proxy_url=proxy_url,
                started_at=state.started_at,
            )

        except Exception as e:
            logger.exception("Failed to start sidecar: %s", e)
            await cleanup_container(container_name)
            raise

    async def stop(self, handle: SidecarHandle) -> None:
        """Stop sidecar proxy container.

        Args:
            handle: Handle from start()
        """
        async with self._lock:
            state = self._sidecars.pop(handle.sidecar_id, None)

        if state is None:
            logger.warning("Sidecar not found: %s", handle.sidecar_id[:12])
            return

        logger.info("Stopping sidecar (id=%s)", handle.sidecar_id[:12])
        await cleanup_container(state.container_name)

    async def configure_tokens(
        self,
        handle: SidecarHandle,
        tokens: dict[TokenType, str],
        ttl_seconds: int,
    ) -> None:
        """Configure tokens for injection by sidecar.

        Sends token configuration to the sidecar's admin API.

        Args:
            handle: Sidecar handle
            tokens: Token type -> token value mapping
            ttl_seconds: Token validity duration
        """
        state = self._sidecars.get(handle.sidecar_id)
        if state is None:
            logger.warning("Sidecar not found for token config: %s", handle.sidecar_id[:12])
            return

        # In production, this would call the sidecar's admin API
        # For now, we log the configuration
        logger.info(
            "Configuring tokens for sidecar (id=%s, types=%s, ttl=%d)",
            handle.sidecar_id[:12],
            [str(t) for t in tokens],
            ttl_seconds,
        )

        # TODO: Call sidecar admin API to configure tokens
        # The sidecar's ext_authz filter will use these tokens
        # to inject Authorization headers into outbound requests

    async def health_check(self, handle: SidecarHandle) -> bool:
        """Check if sidecar is healthy.

        Args:
            handle: Sidecar handle

        Returns:
            True if sidecar is running and healthy
        """
        state = self._sidecars.get(handle.sidecar_id)
        if state is None:
            return False

        # Check container is running
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

