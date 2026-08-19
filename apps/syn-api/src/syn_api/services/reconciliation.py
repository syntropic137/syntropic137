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


async def _docker_stop_bounded(ids: list[str], label: str) -> None:
    """Best-effort graceful stop so capability finalizers get their signal path.

    Separated from _docker_rm so neither function has to carry both the stop
    policy and the removal policy; together they exceeded the cyclomatic budget.

    Never raises and never blocks reaping: the caller force-removes regardless.
    What it must NOT do is stay quiet, because a swallowed stop failure is
    exactly the silent capture loss the stop exists to prevent.
    """
    stop_first = await asyncio.create_subprocess_exec(
        "docker",
        "stop",
        "-t",
        "5",
        *ids,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        _, stop_err = await asyncio.wait_for(stop_first.communicate(), timeout=20)
    except TimeoutError:
        stop_first.kill()
        await stop_first.wait()
        logger.warning(
            "docker stop timed out after 20s for %d %s container(s); forcing "
            "removal, any pending session capture in them is lost",
            len(ids),
            label,
        )
        return

    if stop_first.returncode != 0:
        logger.warning(
            "docker stop exited %s for %s container(s) %s; forcing removal. "
            "Finalizers may not have run, so any pending session capture in "
            "them is lost. stderr: %s",
            stop_first.returncode,
            label,
            ids,
            (stop_err or b"").decode(errors="replace")[:500].strip(),
        )


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

        await _docker_stop_bounded(ids, label)

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
            logger.warning(
                "docker rm -f timed out for %d %s container(s); they may still exist",
                len(ids),
                label,
            )
            return
        # Only claim removal when it actually succeeded. Reporting "Removed N"
        # off the back of an unchecked return code is how an operator concludes
        # cleanup worked while containers are still running.
        if stop_proc.returncode == 0:
            logger.info("Removed %d orphaned %s container(s)", len(ids), label)
        else:
            logger.warning(
                "docker rm -f exited %s for %s container(s) %s; some may still exist",
                stop_proc.returncode,
                label,
                ids,
            )
    except Exception:
        logger.debug("Container cleanup skipped for %s (docker may not be available)", label)
