"""Control plane for execution management.

Provides pause/resume/cancel functionality with hexagonal architecture.

Usage:
    from aef_adapters.control import ExecutionController, PauseExecution

    controller = ExecutionController(state_port, signal_port)
    result = await controller.handle_command(PauseExecution(execution_id="..."))
"""

from aef_adapters.control.commands import (
    CancelExecution,
    ControlCommand,
    ControlResult,
    ControlSignal,
    ControlSignalType,
    InjectContext,
    PauseExecution,
    ResumeExecution,
)
from aef_adapters.control.controller import ExecutionController
from aef_adapters.control.ports import ControlStatePort, SignalQueuePort
from aef_adapters.control.state_machine import (
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
