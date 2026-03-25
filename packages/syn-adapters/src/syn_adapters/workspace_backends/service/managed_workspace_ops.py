"""ManagedWorkspace operation helpers.

Extracted from managed_workspace.py to reduce module complexity.
Contains setup/teardown and interrupt operations.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
        IsolationHandle,
    )

logger = logging.getLogger(__name__)


async def _send_sigint(container_id: str) -> bool:
    """Execute docker exec to send SIGINT, returning True on success."""
    proc = await asyncio.create_subprocess_exec(
        "docker",
        "exec",
        container_id,
        "sh",
        "-c",
        "PID=$(pgrep -n claude) && kill -INT $PID",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        await asyncio.wait_for(proc.communicate(), timeout=5.0)
    except TimeoutError:
        logger.warning(
            "interrupt(): docker exec timed out while sending SIGINT to %s, killing subprocess",
            container_id,
        )
        proc.kill()
        await proc.wait()
        return False

    success = proc.returncode == 0
    if success:
        logger.info("interrupt(): SIGINT delivered to claude process in %s", container_id)
    else:
        logger.warning(
            "interrupt(): no claude process found or SIGINT failed (exit=%d) for container %s",
            proc.returncode,
            container_id,
        )
    return success


async def interrupt_container(isolation_handle: IsolationHandle) -> bool:
    """Send SIGINT to the Claude CLI process inside the container.

    Uses docker exec to find and signal the claude process:
        docker exec <container> sh -c "kill -INT $(pgrep -n claude)"

    Returns True if signal was delivered successfully. Non-fatal on failure
    so cleanup can continue even if the process is already gone.
    """
    container_id = getattr(isolation_handle, "container_id", None)
    if not container_id:
        logger.warning("interrupt(): no container_id on isolation handle, skipping SIGINT")
        return False

    try:
        return await _send_sigint(container_id)
    except Exception as e:
        logger.warning("interrupt(): failed to send SIGINT to %s: %s", container_id, e)
        return False
