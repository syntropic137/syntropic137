"""Completing a phase: the guard, the result, the save, the teardown (#1184).

The processor's COMPLETE_PHASE handler, lifted out whole so that the order of
its four steps is one function's body rather than a method among the drain's
plumbing. The journal is a parameter because a claimed run saves through its
own fold's journal (ADR-072 D8, #1310 1.4), not the processor's shared one.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syn_domain.contexts.orchestration.slices.execute_workflow.phase_outcome import (
    completed_phase,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.unpushed_work_guard import (
    refuse_to_complete_unsaved_phase,
)

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration._shared.TodoValueObjects import TodoItem
    from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
        WorkflowExecutionAggregate,
    )
    from syn_domain.contexts.orchestration.slices.execute_workflow.execution_journal import (
        ExecutionJournal,
    )
    from syn_domain.contexts.orchestration.slices.execute_workflow.phase_runtime import (
        PhaseRuntime,
    )
    from syn_domain.contexts.orchestration.slices.execute_workflow.processor_types import (
        ExecutablePhase,
        PhaseResult,
    )


async def complete_phase(
    todo: TodoItem,
    phase: ExecutablePhase,
    aggregate: WorkflowExecutionAggregate,
    phase_results: list[PhaseResult],
    completed_phase_ids: list[str],
    *,
    runtime: PhaseRuntime,
    journal: ExecutionJournal,
) -> None:
    """Dispatch COMPLETE_PHASE.

    THE ORDER OF THE FOUR STEPS BELOW IS THE GUARANTEE (#1184). The guard
    runs before the phase gives anything up, before the aggregate is told
    it succeeded, before that is persisted, and before the runtime tears
    the workspace down. Every one of those is a point of no return, and the
    guard is only a guard on the near side of all four.

    `phase` is here for the guard, which cannot tell an authored edit from
    a build tool's side effect without the phase's own declaration (#1308).
    Every other handler already took it; this one dropped it, which is why
    the declaration had nowhere to arrive.
    """
    assert todo.phase_id is not None
    # FIRST, and on the real path rather than inside a try: nothing has
    # been popped, the workspace is still alive and the aggregate has not
    # been told this phase succeeded, so the raise IS the outcome (#1184).
    await refuse_to_complete_unsaved_phase(
        runtime.live_workspaces,
        todo,
        delivers_repo_changes=phase.delivers_repo_changes,
    )

    harvest = runtime.harvest(todo.execution_id, todo.phase_id)
    outcome = completed_phase(
        execution_id=todo.execution_id,
        workflow_id=aggregate.workflow_id or "",
        phase_id=todo.phase_id,
        session_id=todo.session_id,
        started_at=harvest.started_at,
        artifact_ids=harvest.artifact_ids,
        auth_tokens=harvest.auth_tokens,
    )
    phase_results.append(outcome.result)
    completed_phase_ids.append(todo.phase_id)

    aggregate.complete_phase(outcome.command)
    await journal.append(aggregate)

    await runtime.finalize(
        todo.phase_id,
        input_tokens=outcome.input_tokens,
        output_tokens=outcome.output_tokens,
        cache_creation_tokens=outcome.cache_creation_tokens,
        cache_read_tokens=outcome.cache_read_tokens,
        total_tokens=outcome.total_tokens,
        duration_seconds=outcome.duration_seconds,
    )
