"""Orphaned session, execution and container cleanup on startup."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
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


def _started_before(summary: object, cutoff: datetime) -> bool:
    """Whether this execution demonstrably started before `cutoff`.

    Returns False when `started_at` is missing or unparseable. Fails CLOSED:
    an execution whose start time cannot be established is left alone rather
    than failed, because the cost of leaving a zombie is a stale row and the
    cost of getting this wrong is killing live work.
    """
    raw = getattr(summary, "started_at", None)
    if isinstance(raw, str):
        try:
            raw = datetime.fromisoformat(raw)
        except ValueError:
            return False
    if not isinstance(raw, datetime):
        return False
    if raw.tzinfo is None:
        raw = raw.replace(tzinfo=UTC)
    return raw < cutoff


async def reconcile_orphaned_executions(
    cleanup: CleanupResult, *, started_before: datetime
) -> None:
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

    TWO GUARDS, both added after review found the first version unsafe.

    `cleanup` is the reap's own report. If the reap could not be shown to have
    finished - docker unreachable, a timeout, a non-zero `docker rm` - then
    "no container can still be running" is not established and this refuses to
    fail anything. The first version called the reap for its side effect and
    read nothing back, so a total loss of docker reachability was a DEBUG line
    followed by every running execution being failed.

    `started_before` is this process's start time. Nothing that began after we
    started can have been orphaned BY us, and the read model cannot tell the two
    apart - both are simply RUNNING. Without this bound, an execution dispatched
    during startup is a candidate: the subscription coordinator and the GitHub
    pollers can dispatch work in this same event loop, so the race does not need
    a second process, which is what the first version's "single-writer
    assumption" note got wrong.
    """
    if not cleanup.fully_reaped:
        logger.warning(
            "Skipping execution reconciliation: the container reap did not complete (%s). "
            "Stranded executions stay 'running' rather than being failed on the strength "
            "of a reap that may have removed nothing.",
            "; ".join(cleanup.failures) or "reason not recorded",
        )
        return

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

    stranded = [row for row in stranded if _started_before(row, started_before)]
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
                    # The phase that was mid-flight, so both phase read models
                    # terminalise it. With None they skip phase mutation
                    # entirely and the phase stays "running" under a "failed"
                    # execution, forever - PhaseCompleted is their only other
                    # writer (#1036).
                    failed_phase_id=aggregate.running_phase_id,
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


@dataclass(frozen=True)
class CleanupResult:
    """Whether the startup reap can be relied on by what runs after it.

    `fully_reaped` is False whenever ANY selector could not be shown to have
    finished: a `docker ps` timeout, a `docker rm -f` timeout or non-zero exit,
    or docker being unreachable at all. It is deliberately pessimistic - the
    only safe reading of "I could not tell" is "containers may still be
    running", because the caller uses this to decide whether it is allowed to
    declare other people's work dead (#1120).
    """

    fully_reaped: bool
    failures: tuple[str, ...] = ()


async def cleanup_orphaned_containers() -> CleanupResult:
    """Stop and remove agent containers left running from a previous framework instance.

    Targets:
    - Sidecar containers: label syn.component=sidecar
    - Workspace containers: name prefix agentic-ws-
    """
    failures: list[str] = []
    for selector, label in (
        ("label=syn.component=sidecar", "sidecar"),
        ("name=agentic-ws-", "workspace"),
    ):
        failure = await _docker_rm(selector, label)
        if failure is not None:
            failures.append(failure)
    if failures:
        logger.warning("Startup container reap did not complete: %s", "; ".join(failures))
    return CleanupResult(fully_reaped=not failures, failures=tuple(failures))


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


async def _docker_rm(filter_arg: str, label: str) -> str | None:
    """Find and force-remove Docker containers matching *filter_arg*.

    Returns None when the reap is known to have finished, or a short reason
    when it is NOT known to have finished. Every path that used to `return`
    quietly now names itself, because "the call returned" was being read
    downstream as "the containers are gone" (#1120).

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
            return f"{label}: `docker ps` timed out"
        ids = stdout.decode().split() if stdout else []
        if not ids:
            return None

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
            return f"{label}: `docker rm -f` timed out on {len(ids)} container(s)"
        # Only claim removal when it actually succeeded. Reporting "Removed N"
        # off the back of an unchecked return code is how an operator concludes
        # cleanup worked while containers are still running.
        if stop_proc.returncode == 0:
            logger.info("Removed %d orphaned %s container(s)", len(ids), label)
            return None
        logger.warning(
            "docker rm -f exited %s for %s container(s) %s; some may still exist",
            stop_proc.returncode,
            label,
            ids,
        )
        return f"{label}: `docker rm -f` exited {stop_proc.returncode}"
    except Exception:
        # NOT debug. Losing docker entirely used to be a DEBUG line, and the
        # execution reconcile then failed every running execution on the
        # strength of a reap that did nothing (#1120).
        logger.warning(
            "Container cleanup for %s could not run (docker may be unreachable)",
            label,
            exc_info=True,
        )
        return f"{label}: docker unreachable"
