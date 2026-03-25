"""Execution controller - core domain logic.

Handles control commands and manages execution state.
Uses ports for I/O - no direct dependencies on storage or messaging.
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

    _COMMAND_DISPATCH: ClassVar[dict[type[ControlCommand], str]] = {
        PauseExecution: "_handle_pause",
        ResumeExecution: "_handle_resume",
        CancelExecution: "_handle_cancel",
        InjectContext: "_handle_inject",
    }

    async def handle_command(self, cmd: ControlCommand) -> ControlResult:
        """Handle a control command and return result."""
        try:
            handler_name = self._COMMAND_DISPATCH.get(type(cmd))
            if handler_name is None:
                return ControlResult(
                    success=False,
                    execution_id=getattr(cmd, "execution_id", "unknown"),
                    new_state="unknown",
                    error=f"Unknown command type: {type(cmd).__name__}",
                )
            handler = getattr(self, handler_name)
            return await handler(cmd)
        except Exception as e:
            logger.exception("Error handling control command")
            return ControlResult(
                success=False,
                execution_id=getattr(cmd, "execution_id", "unknown"),
                new_state="unknown",
                error=str(e),
            )

    async def _handle_pause(self, cmd: PauseExecution) -> ControlResult:
        """Handle pause command."""
        sm = await self._get_state_machine(cmd.execution_id)

        if not sm.can_pause():
            return ControlResult(
                success=False,
                execution_id=cmd.execution_id,
                new_state=sm.state.value,
                error=f"Cannot pause execution in state {sm.state.value}",
            )

        # Queue signal for executor to pick up
        signal = ControlSignal(
            signal_type=ControlSignalType.PAUSE,
            execution_id=cmd.execution_id,
            reason=cmd.reason,
        )
        await self._signal_port.enqueue(cmd.execution_id, signal)

        # Note: State transition happens when executor acknowledges
        return ControlResult(
            success=True,
            execution_id=cmd.execution_id,
            new_state=sm.state.value,  # Still running until acknowledged
            message="Pause signal queued",
        )

    async def _handle_resume(self, cmd: ResumeExecution) -> ControlResult:
        """Handle resume command."""
        sm = await self._get_state_machine(cmd.execution_id)

        if not sm.can_resume():
            return ControlResult(
                success=False,
                execution_id=cmd.execution_id,
                new_state=sm.state.value,
                error=f"Cannot resume execution in state {sm.state.value}",
            )

        signal = ControlSignal(
            signal_type=ControlSignalType.RESUME,
            execution_id=cmd.execution_id,
        )
        await self._signal_port.enqueue(cmd.execution_id, signal)

        return ControlResult(
            success=True,
            execution_id=cmd.execution_id,
            new_state=sm.state.value,
            message="Resume signal queued",
        )

    async def _handle_cancel(self, cmd: CancelExecution) -> ControlResult:
        """Handle cancel command."""
        sm = await self._get_state_machine(cmd.execution_id)

        if not sm.can_cancel():
            return ControlResult(
                success=False,
                execution_id=cmd.execution_id,
                new_state=sm.state.value,
                error=f"Cannot cancel execution in state {sm.state.value}",
            )

        signal = ControlSignal(
            signal_type=ControlSignalType.CANCEL,
            execution_id=cmd.execution_id,
            reason=cmd.reason,
        )
        await self._signal_port.enqueue(cmd.execution_id, signal)

        return ControlResult(
            success=True,
            execution_id=cmd.execution_id,
            new_state=sm.state.value,
            message="Cancel signal queued",
        )

    async def _handle_inject(self, cmd: InjectContext) -> ControlResult:
        """Handle inject context command."""
        sm = await self._get_state_machine(cmd.execution_id)

        if sm.is_terminal:
            return ControlResult(
                success=False,
                execution_id=cmd.execution_id,
                new_state=sm.state.value,
                error="Cannot inject into terminal execution",
            )

        signal = ControlSignal(
            signal_type=ControlSignalType.INJECT,
            execution_id=cmd.execution_id,
            inject_message=cmd.message,
        )
        await self._signal_port.enqueue(cmd.execution_id, signal)

        return ControlResult(
            success=True,
            execution_id=cmd.execution_id,
            new_state=sm.state.value,
            message="Context injection queued",
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
