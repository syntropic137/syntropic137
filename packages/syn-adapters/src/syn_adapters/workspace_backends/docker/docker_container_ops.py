"""Docker container operations - low-level helpers for container management.

Extracted from DockerSidecarAdapter to reduce class complexity.
These are stateless utility functions that operate on containers by name/ID.

See ADR-022: Secure Token Architecture
"""

from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)


async def get_container_network(container_id: str) -> str:
    """Get the Docker network a container is attached to.

    Args:
        container_id: Docker container ID

    Returns:
        Network name, or "syn-workspace-net" as fallback
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            "docker",
            "inspect",
            "-f",
            "{{range $k, $v := .NetworkSettings.Networks}}{{$k}}{{end}}",
            container_id,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        network = stdout.decode().strip()
        if network:
            return network
    except Exception:
        pass

    # Fallback to default network
    return "syn-workspace-net"


async def wait_for_healthy(container_name: str, timeout: float = 30.0) -> None:
    """Wait for a container to be healthy (running state).

    Args:
        container_name: Docker container name
        timeout: Maximum seconds to wait

    Raises:
        RuntimeError: If container does not start within timeout
    """
    import time

    start = time.monotonic()
    while time.monotonic() - start < timeout:
        # Check if container is running
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
            # TODO(#276): Also check sidecar health endpoint
            return
        await asyncio.sleep(0.1)

    raise RuntimeError(f"Sidecar {container_name} did not start within {timeout}s")


async def cleanup_container(container_name: str) -> None:
    """Stop and remove a Docker container.

    Args:
        container_name: Docker container name
    """
    # Stop with short timeout
    proc = await asyncio.create_subprocess_exec(
        "docker",
        "stop",
        "-t",
        "2",
        container_name,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    await proc.wait()

    # Force remove
    proc = await asyncio.create_subprocess_exec(
        "docker",
        "rm",
        "-f",
        container_name,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    await proc.wait()
