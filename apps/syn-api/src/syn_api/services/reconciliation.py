"""Orphaned session, execution and container cleanup on startup."""

from __future__ import annotations

import asyncio
import logging
from typing import Final

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


#: Upper bound on how many stranded executions one startup will reconcile.
#: A number rather than "all of them" because this runs before the API serves
#: traffic: a pathological backlog must not turn a restart into an outage. If a
#: startup ever hits this ceiling it says so, and the next restart takes the
#: next batch.
_MAX_ORPHANS_PER_STARTUP: Final[int] = 500

_ORPHAN_REASON: Final[str] = (
    "Orphaned: the API restarted while this execution was running, and its "
    "workspace container was reaped on startup"
)


async def reconcile_orphaned_executions() -> None:
    """Fail executions stranded in 'running' by a restart, through the aggregate.

    WHY (issue #1120). `cleanup_orphaned_containers` reaps every `agentic-ws-`
    container on startup, so after it runs, no execution that predates this
    process can still be executing - there is nothing left to execute it. The
    domain went on claiming otherwise: nine executions sat in 'running' for six
    hours after the v0.28.0-beta.2 deploy, and `POST /executions/{id}/cancel`
    returned 200 without doing anything, because the processor that would act
    on the signal no longer existed.

    That made deploying expensive. Every restart silently converted in-flight
    runs into permanent zombies, so a deploy had to wait for a fully drained
    queue - hours, for hour-long agent phases - or knowingly destroy paid work.

    THROUGH THE AGGREGATE, not the projection. Rewriting the read model would
    leave the aggregate believing the run is live and would be undone by the
    next replay. `FailExecutionCommand` emits `WorkflowFailedEvent`, so the
    correction is in the event stream where every other status transition is.

    The aggregate rejects the command unless it is RUNNING, which is exactly
    the guard wanted here: a projection row lagging behind a terminal aggregate
    is skipped rather than forced.

    SINGLE-WRITER ASSUMPTION. This is safe only because one API instance owns
    the workspaces - the same assumption `cleanup_orphaned_containers` already
    makes when it reaps every workspace container by name prefix. Under two
    live instances both would be wrong together, and this one would fail a peer's
    running work. Worth naming rather than discovering.
    """
    try:
        from syn_adapters.storage.repositories import get_workflow_execution_repository
        from syn_api._wiring import get_projection_mgr
        from syn_domain.contexts.orchestration import ExecutionStatus, FailExecutionCommand

        manager = get_projection_mgr()
        stranded = await manager.workflow_execution_list.get_all(
            limit=_MAX_ORPHANS_PER_STARTUP,
            status_filter=ExecutionStatus.RUNNING,
        )
    except Exception:
        logger.exception("Could not list stranded executions (non-fatal)")
        return

    if not stranded:
        logger.debug("No stranded executions found")
        return

    repository = get_workflow_execution_repository()
    failed = 0
    for summary in stranded:
        execution_id = summary.workflow_execution_id
        try:
            aggregate = await repository.get_by_id(execution_id)
            if aggregate is None:
                logger.warning(
                    "Execution %s is 'running' in the read model but has no "
                    "aggregate; leaving it alone",
                    execution_id,
                )
                continue
            aggregate.fail_execution(
                FailExecutionCommand(
                    execution_id=execution_id,
                    error=_ORPHAN_REASON,
                    error_type="OrphanedByRestart",
                    failed_phase_id=None,
                    completed_phases=summary.completed_phases,
                    total_phases=summary.total_phases,
                )
            )
            await repository.save(aggregate)
            failed += 1
        except Exception:
            logger.exception("Could not reconcile stranded execution %s (continuing)", execution_id)

    logger.warning(
        "Reconciled %d of %d stranded execution(s) -> marked as failed", failed, len(stranded)
    )
    if len(stranded) == _MAX_ORPHANS_PER_STARTUP:
        logger.warning(
            "Hit the %d-execution reconciliation ceiling; more may remain for the next startup",
            _MAX_ORPHANS_PER_STARTUP,
        )


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
