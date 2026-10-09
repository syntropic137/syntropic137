"""How a run that raised is recorded failed, before its workspace goes.

Split from `WorkflowExecutionProcessor`, which decides THAT a run failed and
hands everything the failure needs over explicitly, so nothing here reads the
processor's shared state. Concurrent runs share that processor; every value
below is this run's own.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syn_domain.contexts.orchestration.slices.execute_workflow.errors import SavedWork
from syn_domain.contexts.orchestration.slices.execute_workflow.failure_teardown import (
    record_failure_and_release,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.phase_outcome import (
    failed_phase_outcome,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.pull_request_observation import (
    with_open_pull_requests,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.unpushed_work_guard import (
    already_saved_by_the_completion_gate,
    quarantined_records,
)

if TYPE_CHECKING:
    from datetime import datetime

    from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
        PhaseResult,
    )
    from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
        WorkflowExecutionAggregate,
    )
    from syn_domain.contexts.orchestration.ports.RemoteBranchPort import RemoteBranchPort
    from syn_domain.contexts.orchestration.slices.execute_workflow.errors import ObservedBranches
    from syn_domain.contexts.orchestration.slices.execute_workflow.execution_journal import (
        ExecutionJournal,
    )
    from syn_domain.contexts.orchestration.slices.execute_workflow.phase_runtime import (
        PhaseRuntime,
    )
    from syn_domain.contexts.orchestration.slices.execute_workflow.phase_workspace import (
        PhaseWorkspace,
    )
    from syn_domain.contexts.orchestration.slices.execute_workflow.processor_types import (
        WorkflowExecutionResult,
    )


async def _observe_branches(
    observed: ObservedBranches | None,
    aggregate: WorkflowExecutionAggregate,
    remote_branches: RemoteBranchPort | None,
) -> ObservedBranches | None:
    """The failing phase's branches, with the PR open from each when a forge is wired (#1513)."""
    if remote_branches is None:
        return observed
    repositories = [c.repository for c in aggregate.start_pins.source_commits]
    return await with_open_pull_requests(observed, remote_branches, repositories)


async def record_failed_execution(
    error: Exception,
    aggregate: WorkflowExecutionAggregate,
    *,
    runtime: PhaseRuntime,
    workspaces: PhaseWorkspace,
    journal: ExecutionJournal,
    remote_branches: RemoteBranchPort | None,
    execution_id: str,
    workflow_id: str,
    total_phases: int,
    phase_results: list[PhaseResult],
    all_artifact_ids: list[str],
    completed_phase_ids: list[str],
    started_at: datetime,
    failed_phase_id: str | None,
    kept_artifact_ids: list[str] | None,
) -> WorkflowExecutionResult:
    """Save what would die with the workspace, record the failure, return the failed result.

    ``runtime`` is read by the caller before any await: teardown clears its
    maps, so reading them afterwards timed the phase to the end of cleanup
    and lost the session_id entirely (#1036).
    """
    kept = list(kept_artifact_ids or [])
    for artifact_id in kept:
        if artifact_id not in all_artifact_ids:
            all_artifact_ids.append(artifact_id)
    # BEFORE any await: teardown clears both maps, so reading them
    # afterwards timed the phase to the end of cleanup and lost the
    # session_id entirely (#1036).
    timings = runtime.timings()
    # Read in the same breath as the timings, and for the same reason: the
    # counts are the dying phase's own, and this is the last frame in which
    # anything can still ask for them (#1262). Without this the phase
    # reported zero tokens no matter what it had burned, so an exit 124
    # after 735 tokens - a stall - was indistinguishable from one after
    # 300k, which needed a bigger budget rather than a retry.
    #
    # Asked with `execution_id`, not just the phase: this processor is
    # shared across concurrent dispatches and two runs of one workflow have
    # the same phase ids, so "what did `implement` spend" names two answers.
    # The id is the run's own, so it always names this one's.
    usage = runtime.usage_for(execution_id, failed_phase_id)
    # Before the teardown below, the only window in which either is
    # possible: SAVE what would die with the container (#1231), then read
    # where that leaves the branches (#1200). Saving first is what lets the
    # branch report point at a quarantine ref instead of at nothing.
    #
    # This does not make the phase succeed and must not be read as doing
    # so. `error` is untouched, `failed_phase_outcome` appends to its reason
    # rather than replacing it, and the aggregate is still told the
    # execution failed: a phase killed at its timeout_seconds is still a
    # phase that ran out of time. What changes is only that the time is now
    # the whole of what the timeout costs.
    #
    # The one failure that arrives with the workspace already emptied is
    # the completion gate's own refusal, which quarantined before it raised
    # (#1184). Saving again would push a second, differently-timestamped
    # commit to the same ref, be rejected as a non-fast-forward, and report
    # the work as lost directly under the gate's report that it is not.
    saved = (
        SavedWork()
        if already_saved_by_the_completion_gate(error)
        else await runtime.save_unpushed_work(failed_phase_id, execution_id=execution_id)
    )
    # Whichever of the two saved it, the workflow changes a rescue had to
    # leave out are stored now, while the run still knows them, and
    # pointed at from the failed phase like everything else it kept (#1437).
    records = quarantined_records(error, saved)
    for artifact_id in await workspaces.keep_dropped_workflows(
        records,
        workflow_id=workflow_id,
        phase_id=failed_phase_id,
        execution_id=execution_id,
        session_id=timings.session_ids.get(failed_phase_id or "", ""),
    ):
        kept.append(artifact_id)
        if artifact_id not in all_artifact_ids:
            all_artifact_ids.append(artifact_id)
    observed = await _observe_branches(
        await runtime.observe(failed_phase_id), aggregate, remote_branches
    )
    failure = failed_phase_outcome(
        error,
        failed_phase_id,
        timings.started_at,
        timings.session_ids,
        observed=observed,
        kept_artifact_ids=kept,
        usage=usage,
        saved=saved,
        quarantined=records,
        repositories=[c.repository for c in aggregate.start_pins.source_commits],
    )
    if failure.result is not None:
        phase_results.append(failure.result)

    await record_failure_and_release(
        failure,
        aggregate=aggregate,
        journal=journal,
        runtime=runtime,
        execution_id=execution_id,
        completed_phases=len(completed_phase_ids),
        total_phases=total_phases,
    )
    return failure.execution_result(
        workflow_id,
        execution_id,
        started_at=started_at,
        phase_results=phase_results,
        artifact_ids=all_artifact_ids,
    )
