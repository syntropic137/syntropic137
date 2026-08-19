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
    """Find and force-remove Docker containers matching *filter_arg*.

    On timeout, kills the subprocess to avoid leaking processes.
    """
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
        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
        except TimeoutError:
            proc.kill()
            await proc.wait()
            return
        ids = stdout.decode().split() if stdout else []
        if not ids:
            return

        logger.warning("Stopping %d orphaned %s container(s): %s", len(ids), label, ids)

        # `docker stop` BEFORE `rm -f`, and the log line above is why this
        # matters. It has always said "Stopping"; the command was `rm -f`, which
        # SIGKILLs. Any capability finalizer - session capture in particular -
        # never ran, so a completed agent run could lose its transcript while
        # the operator's log reported a clean stop.
        #
        # A bounded stop gives the entrypoint's finalizers their signal path.
        # -t 5 matches the normal destroy path in agentic-primitives; failures
        # here are deliberately ignored because `rm -f` below is the backstop
        # and reaping must not be blockable by a container that will not stop.
        stop_first = await asyncio.create_subprocess_exec(
            "docker",
            "stop",
            "-t",
            "5",
            *ids,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            await asyncio.wait_for(stop_first.wait(), timeout=20)
        except TimeoutError:
            stop_first.kill()
            await stop_first.wait()
            logger.warning(
                "docker stop timed out for %s container(s); forcing removal, "
                "any pending session capture in them is lost",
                label,
            )

        stop_proc = await asyncio.create_subprocess_exec(
            "docker",
            "rm",
            "-f",
            *ids,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            await asyncio.wait_for(stop_proc.wait(), timeout=30)
        except TimeoutError:
            stop_proc.kill()
            await stop_proc.wait()
            return
        logger.info("Removed %d orphaned %s container(s)", len(ids), label)
    except Exception:
        logger.debug("Container cleanup skipped for %s (docker may not be available)", label)
