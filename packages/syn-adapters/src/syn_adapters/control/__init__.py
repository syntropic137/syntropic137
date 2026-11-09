"""Control plane for execution management.

Provides execution cancel with hexagonal architecture.

Usage:
    from syn_adapters.control import ExecutionController, CancelExecution

    controller = ExecutionController(execution_repository, signal_port)
    result = await controller.handle_command(CancelExecution(execution_id="..."))
"""

from syn_adapters.control.commands import (
    CancelExecution,
    ControlCommand,
    ControlResult,
    ControlSignal,
    ControlSignalType,
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
    "SignalQueuePort",
]
