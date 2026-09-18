"""Record an execution's failure, then give up everything the run still holds.

WHY THIS IS ONE CALL AND NOT THREE. Three things happen when an execution dies:
the failure is appended to its stream, the open sessions are closed as failed,
and the workspaces are reaped. What makes them correct is not any one of them
but the ORDER they happen in and the fact that the last one happens at all -
and a caller that spells them as three statements holds that order by
convention. The convention was wrong twice. The append used to run last, so a
crash anywhere in teardown left no WorkflowFailedEvent and restart
reconciliation could only ever record the status as unknown (#1319); and the
reap used to sit in an `except`, which a cancellation walks straight past.

So the order IS the interface. A caller says "this execution failed, here is
the account of it" and finds out nothing else: not that the append has two
failure modes worth telling apart, not that the session report is allowed to
fail, and not which construct is load-bearing for the reap.

WHAT THIS DOES NOT DECIDE. It does not judge that the execution failed or
describe why - `PhaseFailure` has answered both before this is called,
and nothing here reads the exception or builds a result. Nor is it the only
path that reaps: `run` keeps its own backstop for the cancellations that never
reach a terminal path at all, and `_cancel_execution` closes its sessions as
cancelled without any of this, because the cancelled path has nothing to append
- its event is already on the stream.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

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
    from syn_domain.contexts.orchestration.slices.execute_workflow.phase_outcome import (
        PhaseFailure,
    )
    from syn_domain.contexts.orchestration.slices.execute_workflow.phase_runtime import (
        PhaseRuntime,
    )

logger = logging.getLogger(__name__)


async def record_failure_and_release(
    failure: PhaseFailure,
    *,
    aggregate: WorkflowExecutionAggregate,
    journal: ExecutionJournal,
    runtime: PhaseRuntime,
    execution_id: str,
    completed_phases: int,
    total_phases: int,
) -> None:
    """Append `failure` to the execution's stream, then release what the run holds.

    Returns normally whatever the append and the session report did - both are
    reported and neither is allowed to stop the reap. A `BaseException` from
    either, a shutdown's `CancelledError` above all, goes on propagating once
    the reap has run.
    """
    # RECORDED BEFORE ANYTHING IS TORN DOWN, and this order is the whole of
    # #1319. The exit status exists in exactly one place - this frame - and
    # the teardown below destroys the container that could have been asked
    # again. Reporting the sessions and reaping the workspaces first meant
    # a crash, a cancellation or a session-repository outage anywhere in
    # that teardown left NO WorkflowFailedEvent at all, so restart
    # reconciliation could only ever record the status as unknown. Writing
    # it first costs nothing when the teardown succeeds and is the only
    # thing that survives when it does not.
    fail_cmd = failure.as_command(
        execution_id, completed_phases=completed_phases, total_phases=total_phases
    )
    # THE REAP IS THE OUTER `finally`, AROUND THE DURABLE WRITE AS WELL AS
    # THE SESSION REPORT. Cleanup runs whatever either of them did.
    #
    # `finally` rather than a second `except`, because `except Exception`
    # is not a guarantee: `asyncio.CancelledError` inherits BaseException,
    # so a shutdown arriving inside `journal.append` - or inside the local
    # projection it drives - passes every `except` clause below untouched
    # and leaves this function. With the reap inside the second block, that
    # left the workspace container running after the run it belonged to was
    # gone. An unreported session is a read-model inaccuracy; an unreleased
    # workspace is a leaked container, and only one of them is still
    # costing money an hour later.
    #
    # THIS IS A `finally` AND NEVER AN `except`. Nothing here catches the
    # cancellation: it is reaped against and then allowed to keep
    # propagating. A shutdown that carries on as though it were not
    # cancelled is a worse bug than the container this guards.
    try:
        try:
            aggregate.fail_execution(fail_cmd)
            await journal.append(aggregate)
        except EventsNotRecordedError:
            # Nothing was written. The status this run died with is now
            # unrecoverable, which is the failure #1319 is about - so it is
            # logged as one, and NOT as "the projection is lagging".
            logger.exception(
                "Failure of execution %s was not durably recorded (exit_code=%s) - "
                "the status this run died with is lost",
                execution_id,
                failure.exit_code,
            )
        except Exception:
            # The event IS on the stream; only this run's local to-do list
            # did not take it. An operator can still read what happened,
            # and a read model that is behind must never hold a container
            # open.
            logger.exception(
                "Failure of execution %s was recorded but the local to-do list did not apply it",
                execution_id,
            )

        try:
            await runtime.report_failed(failure.reason)
        except Exception:
            logger.exception("Could not close the sessions of execution %s as failed", execution_id)
    finally:
        await runtime.abandon_all("failure")
