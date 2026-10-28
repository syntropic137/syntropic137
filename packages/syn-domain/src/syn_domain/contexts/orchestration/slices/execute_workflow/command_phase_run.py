"""RUN_AGENT for a command Phase: the processor's half of ADR-078 D3.

Beside the processor rather than in it so the agent path stays as it was. The
same door applies as for an agent (#1321): a Phase that does not reach
collection, cancelled or raised, keeps what it wrote before its workspace is
torn down.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from syn_domain.contexts.orchestration.domain.aggregate_execution.commands import (
    CancelExecutionCommand,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.ArtifactCollector import (
    UnfinishedPhase,
)

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration._shared.TodoValueObjects import TodoItem
    from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
        ExecutablePhase,
    )
    from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
        WorkflowExecutionAggregate,
    )
    from syn_domain.contexts.orchestration.slices.execute_workflow.execution_journal import (
        ExecutionJournal,
    )
    from syn_domain.contexts.orchestration.slices.execute_workflow.handlers.CommandPhaseHandler import (
        CommandPhaseHandler,
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


async def run_command_phase(
    handler: CommandPhaseHandler,
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
        run = await handler.run(todo, phase, workspace, aggregate, journal.append)
    except Exception:
        await keep(UnfinishedPhase.FAILED)
        raise
    if run.cancelled is None:
        return
    await keep(UnfinishedPhase.INTERRUPTED)
    aggregate.cancel_execution(
        CancelExecutionCommand(
            execution_id=todo.execution_id, phase_id=todo.phase_id, reason=run.cancelled
        )
    )
    await journal.append(aggregate)
