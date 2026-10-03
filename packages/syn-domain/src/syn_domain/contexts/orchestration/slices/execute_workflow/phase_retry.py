"""Retry a phase whose agent stream lost only its terminal event (#1335)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
    RetryPhaseCommand,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.CodexStreamProcessor import (
    MISSING_TERMINAL_TURN_REASON,
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

logger = logging.getLogger(__name__)


async def retry_lost_terminal_attempt(
    todo: TodoItem,
    aggregate: WorkflowExecutionAggregate,
    runtime: PhaseRuntime,
    journal: ExecutionJournal,
    *,
    reason: str | None,
    failure: str,
) -> bool:
    """Retry one phase when the stream alone lost its terminal usage event."""
    assert todo.phase_id is not None
    if reason != MISSING_TERMINAL_TURN_REASON:
        return False
    if not aggregate.may_retry_phase(todo.phase_id):
        logger.error(
            "Phase %s has no attempts left; failing the execution (exec=%s)",
            todo.phase_id,
            todo.execution_id,
        )
        return False

    await runtime.abandon_phase(todo.execution_id, todo.phase_id, reason=failure)
    aggregate.retry_phase(
        RetryPhaseCommand(
            execution_id=todo.execution_id,
            phase_id=todo.phase_id,
            reason=failure,
        )
    )
    await journal.append(aggregate)
    logger.warning(
        "Retrying phase %s in place (attempt %d, exec=%s): %s",
        todo.phase_id,
        aggregate.attempts_for(todo.phase_id) + 1,
        todo.execution_id,
        failure,
    )
    return True
