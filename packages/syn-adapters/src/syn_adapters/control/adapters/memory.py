"""In-memory adapters for testing only.

See ADR-060 (docs/adrs/ADR-060-restart-safe-trigger-deduplication.md).
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import TYPE_CHECKING

from syn_adapters.in_memory import InMemoryAdapter

if TYPE_CHECKING:
    from syn_adapters.control.commands import ControlSignal


class InMemorySignalQueueAdapter(InMemoryAdapter):
    """In-memory signal queue for testing.

    WARNING: This adapter is for TESTING ONLY. Signals are not persisted.
    Use Redis-backed adapter for production.

    Implements SignalQueuePort protocol.
    """

    def __init__(self) -> None:
        super().__init__()
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

    async def get_signal(self, execution_id: str) -> ControlSignal | None:
        """Alias for dequeue - get next signal for executor.

        This is the preferred method name for control plane use cases.
        """
        return await self.dequeue(execution_id)

    def clear(self) -> None:
        """Clear all queues (for testing)."""
        self._queues.clear()
