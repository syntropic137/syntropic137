"""In-memory adapters for development and testing.

NOTE: These adapters are for TESTING ONLY. They include environment checks
that will raise an error if used outside of test environment.
See ADR-004 for environment configuration strategy.
"""

from __future__ import annotations

import asyncio
import os
from collections import defaultdict
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from syn_adapters.control.commands import ControlSignal
    from syn_adapters.control.state_machine import ExecutionState


def _assert_test_environment() -> None:
    """Assert that we're running in a test environment.

    In-memory adapters should only be used in tests. For development/production,
    use persistent adapters (e.g., ProjectionControlStateAdapter).

    Raises:
        RuntimeError: If APP_ENVIRONMENT is not set or not 'test'/'development'.
    """
    app_env = os.getenv("APP_ENVIRONMENT", "").lower()

    # Fail explicitly if APP_ENVIRONMENT is not set
    if app_env == "":
        raise RuntimeError(
            "APP_ENVIRONMENT is not set. InMemory adapters can only be used when "
            "APP_ENVIRONMENT is explicitly set to 'test' or 'development'. "
            "Set APP_ENVIRONMENT=test for testing, or use a persistent adapter for production."
        )

    # Only allow 'test' or 'development' environments
    if app_env not in ("test", "development"):
        raise RuntimeError(
            f"InMemory adapters can only be used in test/development environment. "
            f"Current APP_ENVIRONMENT: '{app_env}'. "
            f"Use ProjectionControlStateAdapter for production."
        )


class InMemoryControlStateAdapter:
    """In-memory state storage for testing.

    WARNING: This adapter is for TESTING ONLY. State is not persisted.
    Use ProjectionControlStateAdapter for production.

    Implements ControlStatePort protocol.
    """

    def __init__(self) -> None:
        _assert_test_environment()
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
    """In-memory signal queue for testing.

    WARNING: This adapter is for TESTING ONLY. Signals are not persisted.
    Use Redis-backed adapter for production.

    Implements SignalQueuePort protocol.
    """

    def __init__(self) -> None:
        _assert_test_environment()
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
