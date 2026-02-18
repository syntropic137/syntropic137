"""Control plane for execution management.

Provides pause/resume/cancel functionality with hexagonal architecture.

Usage:
    from syn_adapters.control import ExecutionController, PauseExecution

    controller = ExecutionController(state_port, signal_port)
    result = await controller.handle_command(PauseExecution(execution_id="..."))
"""

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
from syn_adapters.control.controller import ExecutionController
from syn_adapters.control.ports import ControlStatePort, SignalQueuePort
from syn_adapters.control.state_machine import (
    ExecutionState,
    ExecutionStateMachine,
    InvalidTransitionError,
)

__all__ = [
    "CancelExecution",
    "ControlCommand",
    "ControlResult",
    "ControlSignal",
    "ControlSignalType",
    "ControlStatePort",
    "ExecutionController",
    "ExecutionState",
    "ExecutionStateMachine",
    "InjectContext",
    "InvalidTransitionError",
    "PauseExecution",
    "ResumeExecution",
    "SignalQueuePort",
]
