"""Docker sidecar helper functions.

Extracted from docker_sidecar_adapter.py to reduce module complexity.
Contains command building and container launching helpers.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
        SidecarConfig,
    )

logger = logging.getLogger(__name__)


def build_sidecar_docker_cmd(
    config: SidecarConfig,
    container_name: str,
    network_name: str,
    token_service_url: str,
    default_image: str,
) -> list[str]:
    """Build the docker run command for a sidecar container.

    Args:
        config: Sidecar configuration
        container_name: Name for the container
        network_name: Docker network to attach to
        token_service_url: URL of Token Vending Service
        default_image: Default sidecar Docker image

    Returns:
        Command arguments list for docker run.
    """
    env_vars = [
        f"SYN_WORKSPACE_ID={config.workspace_id}",
        f"SYN_TOKEN_SERVICE_URL={token_service_url}",
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

    docker_cmd.append(config.proxy_image or default_image)
    return docker_cmd


async def run_sidecar_container(docker_cmd: list[str]) -> str:
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
