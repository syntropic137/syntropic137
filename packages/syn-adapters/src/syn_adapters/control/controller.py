"""Execution controller - core domain logic.

Handles control commands and manages execution state.
Uses ports for I/O - no direct dependencies on storage or messaging.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING

from syn_adapters.control.commands import (
    CancelExecution,
    ControlCommand,
    ControlResult,
    ControlSignal,
    ControlSignalType,
    InjectContext,
    PauseExecution,
    ResumeExecution,
)
from syn_adapters.control.state_machine import (
    ExecutionState,
    ExecutionStateMachine,
)

if TYPE_CHECKING:
    from syn_adapters.control.ports import ControlStatePort, SignalQueuePort

logger = logging.getLogger(__name__)


class ExecutionController:
    """Controller for execution control commands."""

    def __init__(
        self,
        state_port: ControlStatePort,
        signal_port: SignalQueuePort,
    ) -> None:
        self._state_port = state_port
        self._signal_port = signal_port

    _COMMAND_HANDLERS: dict[type[ControlCommand], str] = {
        PauseExecution: "_handle_pause",
        ResumeExecution: "_handle_resume",
        CancelExecution: "_handle_cancel",
        InjectContext: "_handle_inject",
    }

    async def handle_command(self, cmd: ControlCommand) -> ControlResult:
        """Handle a control command and return result."""
        try:
            return await self._dispatch_command(cmd)
        except Exception as e:
            logger.exception("Error handling control command")
            return self._error_result(cmd, str(e))

    async def _dispatch_command(self, cmd: ControlCommand) -> ControlResult:
        """Dispatch a command to the appropriate handler."""
        handler_name = self._COMMAND_HANDLERS.get(type(cmd))
        if handler_name is None:
            return self._error_result(cmd, f"Unknown command type: {type(cmd).__name__}")
        handler = getattr(self, handler_name)
        return await handler(cmd)

    @staticmethod
    def _error_result(cmd: ControlCommand, error: str) -> ControlResult:
        """Build an error ControlResult."""
        return ControlResult(
            success=False,
            execution_id=getattr(cmd, "execution_id", "unknown"),
            new_state="unknown",
            error=error,
        )

    async def _handle_pause(self, cmd: PauseExecution) -> ControlResult:
        """Handle pause command."""
        sm = await self._get_state_machine(cmd.execution_id)
        guard_error = self._check_guard(sm, sm.can_pause, "pause")
        if guard_error:
            return self._guard_failure(cmd.execution_id, sm, guard_error)

        return await self._enqueue_signal(
            cmd.execution_id, sm,
            ControlSignal(
                signal_type=ControlSignalType.PAUSE,
                execution_id=cmd.execution_id,
                reason=cmd.reason,
            ),
            message="Pause signal queued",
        )

    async def _handle_resume(self, cmd: ResumeExecution) -> ControlResult:
        """Handle resume command."""
        sm = await self._get_state_machine(cmd.execution_id)
        guard_error = self._check_guard(sm, sm.can_resume, "resume")
        if guard_error:
            return self._guard_failure(cmd.execution_id, sm, guard_error)

        return await self._enqueue_signal(
            cmd.execution_id, sm,
            ControlSignal(
                signal_type=ControlSignalType.RESUME,
                execution_id=cmd.execution_id,
            ),
            message="Resume signal queued",
        )

    async def _handle_cancel(self, cmd: CancelExecution) -> ControlResult:
        """Handle cancel command."""
        sm = await self._get_state_machine(cmd.execution_id)
        guard_error = self._check_guard(sm, sm.can_cancel, "cancel")
        if guard_error:
            return self._guard_failure(cmd.execution_id, sm, guard_error)

        return await self._enqueue_signal(
            cmd.execution_id, sm,
            ControlSignal(
                signal_type=ControlSignalType.CANCEL,
                execution_id=cmd.execution_id,
                reason=cmd.reason,
            ),
            message="Cancel signal queued",
        )

    async def _handle_inject(self, cmd: InjectContext) -> ControlResult:
        """Handle inject context command."""
        sm = await self._get_state_machine(cmd.execution_id)
        if sm.is_terminal:
            return self._guard_failure(
                cmd.execution_id, sm, "Cannot inject into terminal execution"
            )

        return await self._enqueue_signal(
            cmd.execution_id, sm,
            ControlSignal(
                signal_type=ControlSignalType.INJECT,
                execution_id=cmd.execution_id,
                inject_message=cmd.message,
            ),
            message="Context injection queued",
        )

    @staticmethod
    def _check_guard(
        sm: ExecutionStateMachine,
        guard_fn: Callable[[], bool],
        action: str,
    ) -> str | None:
        """Return an error message if the guard fails, else None."""
        if not guard_fn():
            return f"Cannot {action} execution in state {sm.state.value}"
        return None

    @staticmethod
    def _guard_failure(
        execution_id: str, sm: ExecutionStateMachine, error: str
    ) -> ControlResult:
        """Build a failure result for a guard check."""
        return ControlResult(
            success=False,
            execution_id=execution_id,
            new_state=sm.state.value,
            error=error,
        )

    async def _enqueue_signal(
        self,
        execution_id: str,
        sm: ExecutionStateMachine,
        signal: ControlSignal,
        *,
        message: str,
    ) -> ControlResult:
        """Enqueue a control signal and return a success result."""
        await self._signal_port.enqueue(execution_id, signal)
        return ControlResult(
            success=True,
            execution_id=execution_id,
            new_state=sm.state.value,
            message=message,
        )

    async def _get_state_machine(self, execution_id: str) -> ExecutionStateMachine:
        """Create a state machine from the current projection state."""
        state = await self._state_port.get_state(execution_id)
        if state:
            return ExecutionStateMachine(state)
        return ExecutionStateMachine()

    async def get_state(self, execution_id: str) -> ExecutionState | None:
        """Get current state for an execution from the projection.

        Returns None if the execution is not known.
        """
        return await self._state_port.get_state(execution_id)

    async def check_signal(self, execution_id: str) -> ControlSignal | None:
        """Check for pending control signal (called by executor)."""
        return await self._signal_port.dequeue(execution_id)

    async def acknowledge_state(self, execution_id: str, new_state: ExecutionState) -> None:
        """Acknowledge state transition (called by executor)."""
        await self._state_port.save_state(execution_id, new_state)

    async def initialize_execution(
        self, execution_id: str, initial_state: ExecutionState = ExecutionState.PENDING
    ) -> None:
        """Initialize state for a new execution."""
        await self._state_port.save_state(execution_id, initial_state)
