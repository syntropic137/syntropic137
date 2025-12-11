"""In-memory adapters for development and testing."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aef_adapters.control.commands import ControlSignal
    from aef_adapters.control.state_machine import ExecutionState


class InMemoryControlStateAdapter:
    """In-memory state storage for development.

    Implements ControlStatePort protocol.
    """

    def __init__(self) -> None:
        self._states: dict[str, ExecutionState] = {}
        self._lock = asyncio.Lock()

    async def save_state(self, execution_id: str, state: ExecutionState) -> None:
        """Save execution state."""
        async with self._lock:
            self._states[execution_id] = state

    async def get_state(self, execution_id: str) -> ExecutionState | None:
        """Get current execution state, or None if not found."""
        return self._states.get(execution_id)

    def clear(self) -> None:
        """Clear all states (for testing)."""
        self._states.clear()


class InMemorySignalQueueAdapter:
    """In-memory signal queue for development.

    Implements SignalQueuePort protocol.
    """

    def __init__(self) -> None:
        self._queues: dict[str, list[ControlSignal]] = defaultdict(list)
        self._lock = asyncio.Lock()

    async def enqueue(self, execution_id: str, signal: ControlSignal) -> None:
        """Add signal to queue for executor to pick up."""
        async with self._lock:
            self._queues[execution_id].append(signal)

    async def dequeue(self, execution_id: str) -> ControlSignal | None:
        """Get and remove next signal for execution, or None if empty."""
        async with self._lock:
            queue = self._queues.get(execution_id, [])
            if queue:
                return queue.pop(0)
            return None

    def clear(self) -> None:
        """Clear all queues (for testing)."""
        self._queues.clear()
