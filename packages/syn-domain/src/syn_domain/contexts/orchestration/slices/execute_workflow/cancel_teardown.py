"""Keep what a cancelled phase left, record it for the PR, then give up the run.

The cancelled counterpart of `failure_teardown`: the cancel itself is already
on the stream, so nothing here appends it. What is appended is what the save
landed (#1547), and the order is the same rule as there - everything that needs
the container happens BEFORE `abandon_all` destroys it, and the reap is a
`finally` so a shutdown cannot walk past it.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from syn_domain.contexts.orchestration.slices.execute_workflow.phase_outcome import (
    cancelled_execution,
)

if TYPE_CHECKING:
    from datetime import datetime

    from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
        WorkflowExecutionAggregate,
    )
    from syn_domain.contexts.orchestration.slices.execute_workflow.cancelled_work_record import (
        CancelledWorkLedger,
    )
    from syn_domain.contexts.orchestration.slices.execute_workflow.phase_runtime import (
        PhaseRuntime,
    )
    from syn_domain.contexts.orchestration.slices.execute_workflow.phase_workspace import (
        PhaseWorkspace,
    )
    from syn_domain.contexts.orchestration.slices.execute_workflow.processor_types import (
        PhaseResult,
        WorkflowExecutionResult,
    )

logger = logging.getLogger(__name__)


async def record_cancel_and_release(
    *,
    aggregate: WorkflowExecutionAggregate,
    runtime: PhaseRuntime,
    workspaces: PhaseWorkspace,
    ledger: CancelledWorkLedger,
    workflow_id: str,
    execution_id: str,
    phase_id: str | None,
    cancel_reason: str | None,
    phase_results: list[PhaseResult],
    all_artifact_ids: list[str],
    started_at: datetime,
) -> WorkflowExecutionResult:
    """Save, keep and record the cancelled phase's work, close its sessions, reap."""
    session_ids = runtime.timings().session_ids
    # BEFORE the teardown below. `abandon_all` destroys the cancelled
    # phase's container and commits that exist only in it go with it. The
    # user asked for the run to stop, not for the work to be deleted
    # (#1231).
    try:
        saved = await runtime.save_unpushed_work(phase_id, execution_id=execution_id)
        # The workflow changes the rescue could not push, stored while
        # this is still the run that knows them (#1437). No inputs: they
        # are read only to provision, and storing an artifact is not that.
        dropped = await workspaces.keep_dropped_workflows(
            saved.quarantined,
            workflow_id=workflow_id,
            phase_id=phase_id,
            execution_id=execution_id,
            session_id=session_ids.get(phase_id or "", ""),
        )
        all_artifact_ids.extend(i for i in dropped if i not in all_artifact_ids)
        cancellation = cancelled_execution(
            cancel_reason,
            phase_results,
            all_artifact_ids,
            saved=saved,
            repositories=[c.repository for c in aggregate.start_pins.source_commits],
        )
        command = cancellation.as_command(execution_id, phase_id)
        recorded = await ledger.record(aggregate, command)
        try:
            await runtime.report_cancelled(cancellation.reason)
        except Exception:
            logger.exception("Could not close the cancelled sessions of %s", execution_id)
        return cancellation.execution_result(
            workflow_id, execution_id, started_at=started_at, recorded=recorded
        )
    finally:
        await runtime.abandon_all("cancel")
