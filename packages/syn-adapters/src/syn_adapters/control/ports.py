"""Port definitions for control plane.

Ports are abstract interfaces that the domain depends on.
Adapters implement these for specific technologies.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from syn_adapters.control.commands import ControlSignal


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
