"""RUN_AGENT for a command Phase: the processor's half of ADR-078 D3.

Beside the processor rather than in it so the agent path stays as it was. The
same door applies as for an agent (#1321): a Phase that does not reach
collection, cancelled or raised, keeps what it wrote before its workspace is
torn down.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Protocol

from syn_domain.contexts.orchestration.domain.aggregate_execution.commands import (
    CancelExecutionCommand,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    ExecutionMetrics,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.ArtifactCollector import (
    UnfinishedPhase,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.handlers.CommandPhaseHandler import (
    CommandPhaseHandler,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.processor_types import (
    WorkflowExecutionResult,
)

if TYPE_CHECKING:
    from syn_adapters.control import ExecutionController
    from syn_domain.contexts.orchestration._shared.TodoValueObjects import TodoItem
    from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
        ExecutablePhase,
        PhaseResult,
    )
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


class KeptArtifacts(Protocol):
    """Where the run's dispatch context holds what an unfinished Phase kept."""

    kept_artifact_ids: list[str]


async def record_cancel(
    todo: TodoItem,
    reason: str | None,
    aggregate: WorkflowExecutionAggregate,
    journal: ExecutionJournal,
) -> None:
    """End the Execution as cancelled: a stopped agent or a stopped command step alike."""
    assert todo.phase_id is not None, "phase_id must be set for a running phase todo"
    aggregate.cancel_execution(
        CancelExecutionCommand(
            execution_id=todo.execution_id,
            phase_id=todo.phase_id,
            reason=reason or "Cancelled by user",
        )
    )
    await journal.append(aggregate)


async def run_command_phase(
    controller: ExecutionController | None,
    todo: TodoItem,
    phase: ExecutablePhase,
    aggregate: WorkflowExecutionAggregate,
    *,
    runtime: PhaseRuntime,
    workspaces: PhaseWorkspace,
    journal: ExecutionJournal,
    kept: KeptArtifacts,
) -> None:
    """Run the steps; a cancel ends the Execution as cancelled, keeping the report."""
    assert todo.phase_id is not None, "a command phase to-do names its phase"
    # KeyError, as `PhaseRuntime.launch` raises: RUN_AGENT before
    # PROVISION_WORKSPACE is a broken projection, not something to default.
    workspace = runtime.live_workspaces[todo.phase_id]

    async def keep(outcome: UnfinishedPhase) -> None:
        kept.kept_artifact_ids = await workspaces.keep_unfinished_output(
            todo,
            phase,
            workspace=workspace,
            last_agent_message=None,
            outcome=outcome,
            aggregate=aggregate,
        )

    try:
        run = await CommandPhaseHandler(controller=controller).run(
            todo, phase, workspace, aggregate, journal.append
        )
    except Exception:
        await keep(UnfinishedPhase.FAILED)
        raise
    if run.cancelled is None:
        return
    await keep(UnfinishedPhase.INTERRUPTED)
    await record_cancel(todo, run.cancelled, aggregate, journal)


def gate_failed_result(
    aggregate: WorkflowExecutionAggregate,
    phase_results: list[PhaseResult],
    artifact_ids: list[str],
    started_at: datetime,
) -> WorkflowExecutionResult:
    """The result of a run a command gate ended at collection (ADR-078 D5).

    The aggregate already recorded `WorkflowFailed`, so nothing is recorded
    here: this only says so to the caller, in the gate's own words.
    """
    return WorkflowExecutionResult(
        workflow_id=aggregate.workflow_id or "",
        execution_id=aggregate.id or "",
        status="failed",
        started_at=started_at,
        completed_at=datetime.now(UTC),
        phase_results=phase_results,
        artifact_ids=artifact_ids,
        metrics=ExecutionMetrics.from_results(phase_results),
        error_message=aggregate.error_message,
        failure_classification=aggregate.failure_classification,
    )
