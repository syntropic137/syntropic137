"""Interrupt a fenced run through the WorkflowExecution aggregate (ADR-072 D5 step 3)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Protocol

from syn_domain.contexts.orchestration.domain.aggregate_execution.commands import (
    InterruptExecutionCommand,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    ExecutionStatus,
)

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
        WorkflowExecutionAggregate,
    )
    from syn_domain.contexts.orchestration.ports import FencedRun

logger = logging.getLogger(__name__)


class _Executions(Protocol):
    async def get_by_id(self, aggregate_id: str) -> WorkflowExecutionAggregate | None: ...

    async def save(self, aggregate: WorkflowExecutionAggregate) -> None: ...


class AggregateRunInterrupter:
    """Appends ``WorkflowInterruptedEvent`` unless the aggregate is no longer RUNNING.

    The append is optimistic on the stream version, so whichever of the stalled
    owner and this reconciler writes second gets ``ConcurrencyConflictError``
    and changes nothing: the stream has one terminal event.
    """

    def __init__(self, executions: _Executions) -> None:
        self._executions = executions

    async def interrupt(self, run: FencedRun) -> None:
        aggregate = await self._executions.get_by_id(run.execution_id)
        if aggregate is None:
            msg = f"fenced run {run.execution_id} has no execution stream"
            raise LookupError(msg)
        if aggregate.status is not ExecutionStatus.RUNNING:
            logger.info(
                "Fenced run %s is already %s; closing its row only",
                run.execution_id,
                aggregate.status,
            )
            return
        aggregate.interrupt_execution(
            InterruptExecutionCommand(
                execution_id=run.execution_id,
                phase_id=aggregate.running_phase_id or "",
                reason=f"lease expired: executor {run.executor_id} stopped renewing",
            )
        )
        await self._executions.save(aggregate)
