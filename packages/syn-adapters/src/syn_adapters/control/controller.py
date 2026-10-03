"""Execution controller - admits operator control requests and queues signals.

Uses ports for I/O - no direct dependencies on storage or messaging.

WHO DECIDES (ADR-014 section 7). Whether a request is admissible is the
WorkflowExecution aggregate's decision, asked of the aggregate rehydrated from
its event stream on every request. It used to be decided here, by a state
machine fed from the execution detail PROJECTION. A projection lags the stream
it is derived from, so an execution the aggregate had already cancelled could
still read `running` or `paused`, and a request the aggregate would refuse was
admitted, reported as success and queued. The controller now holds no rule of
its own: it loads, asks, and queues.

It fails closed. An execution with no stream is refused, and an event store
that cannot be read is refused with the error rather than guessed around.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, ClassVar

from syn_adapters.control.commands import (
    CancelExecution,
    ControlCommand,
    ControlResult,
    ControlSignal,
    ControlSignalType,
    InjectContext,
)

if TYPE_CHECKING:
    from syn_adapters.control.ports import SignalQueuePort
    from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
        ExecutionStatus,
    )
    from syn_domain.contexts.orchestration.ports.WorkflowExecutionRepositoryPort import (
        WorkflowExecutionRepositoryPort,
    )

logger = logging.getLogger(__name__)


class ExecutionController:
    """Controller for execution control commands."""

    def __init__(
        self,
        executions: WorkflowExecutionRepositoryPort,
        signal_port: SignalQueuePort,
    ) -> None:
        self._executions = executions
        self._signal_port = signal_port

    #: What each command asks for, and what the operator is told on success.
    _SIGNALS: ClassVar[dict[type[ControlCommand], tuple[ControlSignalType, str]]] = {
        CancelExecution: (ControlSignalType.CANCEL, "Cancel signal queued"),
        InjectContext: (ControlSignalType.INJECT, "Context injection queued"),
    }

    async def handle_command(self, cmd: ControlCommand) -> ControlResult:
        """Admit a control command if the aggregate accepts it, then queue its signal."""
        try:
            return await self._admit(cmd)
        except Exception as e:
            logger.exception("Error handling control command")
            return ControlResult(
                success=False,
                execution_id=getattr(cmd, "execution_id", "unknown"),
                new_state="unknown",
                error=str(e),
            )

    async def _admit(self, cmd: ControlCommand) -> ControlResult:
        entry = self._SIGNALS.get(type(cmd))
        if entry is None:
            return ControlResult(
                success=False,
                execution_id=getattr(cmd, "execution_id", "unknown"),
                new_state="unknown",
                error=f"Unknown command type: {type(cmd).__name__}",
            )
        signal_type, queued_message = entry

        execution = await self._executions.get_by_id(cmd.execution_id)
        if execution is None:
            return ControlResult(
                success=False,
                execution_id=cmd.execution_id,
                new_state="unknown",
                error=f"Execution {cmd.execution_id} not found",
            )

        state = execution.status.value
        if not execution.accepts_control(signal_type):
            return ControlResult(
                success=False,
                execution_id=cmd.execution_id,
                new_state=state,
                error=_refusal(signal_type, state),
            )

        await self._signal_port.enqueue(cmd.execution_id, _signal_for(cmd, signal_type))

        # The state is unchanged until the executor acts on the signal.
        return ControlResult(
            success=True,
            execution_id=cmd.execution_id,
            new_state=state,
            message=queued_message,
        )

    async def get_state(self, execution_id: str) -> ExecutionStatus | None:
        """Get the execution's current status from its event stream.

        Returns None if the execution is not known.
        """
        execution = await self._executions.get_by_id(execution_id)
        return execution.status if execution is not None else None

    async def check_signal(self, execution_id: str) -> ControlSignal | None:
        """Check for pending control signal (called by executor)."""
        return await self._signal_port.dequeue(execution_id)


def _signal_for(cmd: ControlCommand, signal_type: ControlSignalType) -> ControlSignal:
    return ControlSignal(
        signal_type=signal_type,
        execution_id=cmd.execution_id,
        reason=cmd.reason if isinstance(cmd, CancelExecution) else None,
        inject_message=cmd.message if isinstance(cmd, InjectContext) else None,
    )


def _refusal(signal_type: ControlSignalType, state: str) -> str:
    if signal_type is ControlSignalType.INJECT:
        return "Cannot inject into terminal execution"
    return f"Cannot {signal_type.value} execution in state {state}"
