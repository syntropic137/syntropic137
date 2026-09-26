"""Control plane for execution management.

Provides pause/resume/cancel functionality with hexagonal architecture.

Usage:
    from syn_adapters.control import ExecutionController, PauseExecution

    controller = ExecutionController(execution_repository, signal_port)
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
from syn_adapters.control.ports import SignalQueuePort

__all__ = [
    "CancelExecution",
    "ControlCommand",
    "ControlResult",
    "ControlSignal",
    "ControlSignalType",
    "ExecutionController",
    "InjectContext",
    "PauseExecution",
    "ResumeExecution",
    "SignalQueuePort",
]
