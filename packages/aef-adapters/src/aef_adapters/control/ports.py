"""Port definitions for control plane.

Ports are abstract interfaces that the domain depends on.
Adapters implement these for specific technologies.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from aef_adapters.control.commands import ControlSignal
    from aef_adapters.control.state_machine import ExecutionState


class ControlStatePort(Protocol):
    """Port for persisting execution control state."""

    async def save_state(self, execution_id: str, state: ExecutionState) -> None:
        """Save execution state."""
        ...

    async def get_state(self, execution_id: str) -> ExecutionState | None:
        """Get current execution state, or None if not found."""
        ...


class SignalQueuePort(Protocol):
    """Port for queueing control signals to executors."""

    async def enqueue(self, execution_id: str, signal: ControlSignal) -> None:
        """Add signal to queue for executor to pick up."""
        ...

    async def dequeue(self, execution_id: str) -> ControlSignal | None:
        """Get and remove next signal for execution, or None if empty."""
        ...

    async def get_signal(self, execution_id: str) -> ControlSignal | None:
        """Alias for dequeue - get next signal for executor.

        This is the preferred method name for control plane use cases.
        """
        ...
