"""Orphaned session and container cleanup on startup."""

from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)


async def reconcile_orphaned_sessions() -> None:
    """Mark sessions stuck in 'running' as failed on startup.

    Any session still 'running' when the framework starts is orphaned —
    its container was killed and can no longer complete normally.
    """
    try:
        from syn_api._wiring import get_projection_mgr

        manager = get_projection_mgr()
        count = await manager.session_list.reconcile_orphaned()
        if count:
            logger.warning("Reconciled %d orphaned session(s) → marked as failed", count)
        else:
            logger.debug("No orphaned sessions found")
    except Exception:
        logger.exception("Failed to reconcile orphaned sessions (non-fatal)")


async def cleanup_orphaned_containers() -> None:
    """Stop and remove agent containers left running from a previous framework instance.

    Targets:
    - Sidecar containers: label syn.component=sidecar
    - Workspace containers: name prefix agentic-ws-
    """
    await _docker_rm("label=syn.component=sidecar", "sidecar")
    await _docker_rm("name=agentic-ws-", "workspace")


async def _docker_rm(filter_arg: str, label: str) -> None:
    """Find and force-remove Docker containers matching *filter_arg*."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "docker",
            "ps",
            "-q",
            "--filter",
            filter_arg,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
        ids = stdout.decode().split() if stdout else []
        if not ids:
            return

        logger.warning("Stopping %d orphaned %s container(s): %s", len(ids), label, ids)
        stop_proc = await asyncio.create_subprocess_exec(
            "docker",
            "rm",
            "-f",
            *ids,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await asyncio.wait_for(stop_proc.wait(), timeout=30)
        logger.info("Removed %d orphaned %s container(s)", len(ids), label)
    except Exception:
        logger.debug("Container cleanup skipped for %s (docker may not be available)", label)
