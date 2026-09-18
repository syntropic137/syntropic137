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
        raise RuntimeError(
            f"Failed to start sidecar: {_why_docker_run_failed(proc.returncode, stdout, stderr)}"
        )

    return stdout.decode().strip()


def _why_docker_run_failed(returncode: int | None, stdout: bytes, stderr: bytes) -> str:
    """Everything the failed `docker run` still knows about why it failed.

    The status is what decided this was a failure, so throwing it away leaves
    a message that cannot tell "image missing" from "out of disk" from "daemon
    unreachable" (#1247, and the same shape upstream in the isolation
    provider's `create`). It used to be replaced by the literal string
    "Unknown error", which is what a real provisioning failure reported and
    why that failure is still unattributed.

    Two things this gets deliberately right, both of which have been got wrong
    before:

    * **A missing status is not a zero.** `returncode` is typed optional and
      zero reads as success, so the absent case says it is absent rather than
      quietly claiming the command succeeded while we raise about it (#1341).
    * **The status belongs to the local `docker` client, not the container.**
      CPython reports a signal death of its own child as negative, while a
      process killed *inside* a container comes back through Docker as a
      positive 128+N - so -11 and 139 are the same event with opposite signs,
      and a reader who does not know which process the number describes cannot
      tell them apart (#1295). Naming the process is what disambiguates it;
      this is not the place that names signals.
    """
    if returncode is None:
        status = "the local `docker run` client has no exit status (it was never reaped)"
    else:
        status = f"the local `docker run` client exited {returncode}"

    # stderr first, but docker does not reliably use it, and stdout carrying
    # the reason is worth more than a sentence saying there was no reason.
    detail = stderr.decode().strip() or stdout.decode().strip()
    return f"{status}: {detail}" if detail else f"{status} and wrote nothing to stdout or stderr"
