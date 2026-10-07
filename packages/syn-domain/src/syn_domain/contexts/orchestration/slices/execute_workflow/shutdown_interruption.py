"""Record a run the platform is shutting down under as INTERRUPTED, within a budget (#1381).

WHY THIS EXISTS. A shutdown cancels every execution task. `CancelledError` is a
BaseException, so it walked past both terminal paths that save a phase's work -
the cancel path and the fail path - straight into `abandon_all`, which destroys
the container. Commits that lived only there went with it, and the execution
was left RUNNING for the next start's reconciler to call `OrphanedByRestart`.

WHAT THE CALLER GETS. One call, `preserve_interrupted_run`, that returns only
when either the interruption is on the stream or the budget is spent, and that a
second cancel cannot cut short. The caller tears down after it and re-raises;
it never learns that the sequence ran as its own task, or how long anything in
it was allowed to take.

WHY INTERRUPTED. The orchestration vocabulary groups FAILED and INTERRUPTED as
"ended without anyone deciding the work should stop", and INTERRUPTED is the
platform's own word for it. It is resumable (`resume_rules.RESUMABLE_STATUSES`).

WHAT IT DELIBERATELY DOES NOT DO. It never retries the append: a store that
refused it during shutdown is a store that will not be there in a moment, and
the startup reconciler already gives an execution left RUNNING the honest
account. Nor does it close sessions: the next process cannot tell a session it
closed from one it never saw, and reconciliation closes both alike.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import TYPE_CHECKING, Final

from syn_domain.contexts.orchestration.domain.aggregate_execution.commands import (
    InterruptExecutionCommand,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    ExecutionStatus,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.errors import describe_saved_work
from syn_domain.contexts.orchestration.slices.execute_workflow.execution_journal import (
    EventsNotRecordedError,
)

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
        WorkflowExecutionAggregate,
    )
    from syn_domain.contexts.orchestration.slices.execute_workflow.execution_journal import (
        ExecutionJournal,
    )
    from syn_domain.contexts.orchestration.slices.execute_workflow.phase_runtime import (
        PhaseRuntime,
    )
    from syn_domain.contexts.orchestration.slices.execute_workflow.phase_workspace import (
        PhaseWorkspace,
    )

logger = logging.getLogger(__name__)

#: The reason recorded on the event. A shutdown is not a user's decision and
#: not the run's fault; this says which of the three it was.
SHUTDOWN_REASON: Final[str] = "Interrupted by platform shutdown"

#: How long a sequence cut off at the budget is still waited for, so teardown
#: never removes a container while a salvage push is reading from it. The
#: rescue in `unpushed_work_guard` honours a cancel only after its own post-
#: cancel bounds: the push (30 s), the workflow-safe rescue (60 s) and the
#: diffstat (5 s). This is their sum, so it is the longest the cancel can be
#: ignored, and the compose `stop_grace_period` is sized against it plus the
#: budget. A module global read at call time, so a test can shorten it.
_SETTLE_AFTER_CANCEL_SECONDS: float = 95.0


async def preserve_interrupted_run(
    *,
    aggregate: WorkflowExecutionAggregate,
    runtime: PhaseRuntime,
    workspaces: PhaseWorkspace,
    journal: ExecutionJournal,
    workflow_id: str,
    execution_id: str,
    phase_id: str | None,
    kept_artifact_ids: list[str],
    budget_seconds: float,
) -> None:
    """Save the phase's work and record the run INTERRUPTED, awaited, bounded, uncancellable.

    Further cancels that arrive while this waits are absorbed and the wait goes
    on: shutdown cancels and then cancels again, and a second cancel must not be
    what decides whether the work is saved. Past `budget_seconds` the sequence
    is cancelled and its settling awaited, and the run stays RUNNING for the
    startup reconciler.
    """
    if aggregate.status is not ExecutionStatus.RUNNING:
        # It had already ended - the cancel landed inside its own terminal
        # path - and an interruption would contradict what is on the stream.
        return
    # BEFORE any await, for the reason `_fail_execution` gives (#1036, #1262):
    # these are the dying phase's own, and teardown clears them.
    usage = runtime.usage_for(execution_id, phase_id)
    session_ids = runtime.timings().session_ids

    async def interrupt() -> None:
        saved = await runtime.save_unpushed_work(phase_id, execution_id=execution_id)
        kept = list(kept_artifact_ids)
        for artifact_id in await workspaces.keep_dropped_workflows(
            saved.quarantined,
            workflow_id=workflow_id,
            phase_id=phase_id,
            execution_id=execution_id,
            session_id=session_ids.get(phase_id or "", ""),
        ):
            if artifact_id not in kept:
                kept.append(artifact_id)
        reason = SHUTDOWN_REASON
        if saved.is_worth_reporting:
            reason = f"{reason}\n\n{describe_saved_work(saved)}"
        aggregate.interrupt_execution(
            InterruptExecutionCommand(
                execution_id=execution_id,
                # Empty when shutdown landed between phases: no phase was in
                # flight, and naming the next one would claim it had started.
                phase_id=phase_id or "",
                partial_artifact_ids=kept,
                reason=reason,
                partial_input_tokens=usage.input_tokens,
                partial_output_tokens=usage.output_tokens,
            )
        )
        await journal.append(aggregate)

    sequence = asyncio.create_task(interrupt(), name=f"interrupt-{execution_id}")
    if not await _wait_through_cancels(sequence, budget_seconds):
        logger.error(
            "Execution %s was not recorded as interrupted within %.0fs of shutdown; "
            "it stays running for startup reconciliation",
            execution_id,
            budget_seconds,
        )
        sequence.cancel()
        if not await _wait_through_cancels(sequence, _SETTLE_AFTER_CANCEL_SECONDS):
            logger.error(
                "Execution %s: the interrupted phase's salvage did not settle; "
                "tearing its workspace down anyway",
                execution_id,
            )
        return
    _report_unrecorded(sequence, execution_id)


async def _wait_through_cancels(task: asyncio.Task[None], seconds: float) -> bool:
    """Wait up to `seconds` for `task`, absorbing cancels; whether it finished.

    `asyncio.wait` never cancels what it waits on, so a cancel landing here
    interrupts only this wait, and the loop takes it up again against the same
    deadline. The deadline is what bounds it; a cancel is not.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + seconds
    while not task.done() and (remaining := deadline - loop.time()) > 0:
        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.wait({task}, timeout=remaining)
    return task.done()


def _report_unrecorded(sequence: asyncio.Task[None], execution_id: str) -> None:
    """Log at ERROR when the finished sequence did not land the interruption."""
    if sequence.cancelled():
        return
    error = sequence.exception()
    if isinstance(error, EventsNotRecordedError):
        # Not retried: the reconciler gives a run left RUNNING its account.
        logger.error(
            "Execution %s: the event store refused its interruption, so it stays "
            "running for startup reconciliation: %s",
            execution_id,
            error,
        )
    elif error is not None:
        logger.error(
            "Execution %s could not be recorded as interrupted at shutdown",
            execution_id,
            exc_info=error,
        )
