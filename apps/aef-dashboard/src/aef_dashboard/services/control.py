"""Control plane service factory."""

from __future__ import annotations

import os
from functools import lru_cache
from typing import TYPE_CHECKING

from aef_adapters.control import ExecutionController
from aef_adapters.control.adapters.projection import ProjectionControlStateAdapter
from aef_adapters.projection_stores import get_projection_store

if TYPE_CHECKING:
    from aef_adapters.control.ports import SignalQueuePort

# Global adapter instances (shared across controller instances)
_state_adapter: ProjectionControlStateAdapter | None = None
_signal_adapter: SignalQueuePort | None = None


class NullSignalQueueAdapter:
    """No-op signal adapter for development when Redis is not available.

    This allows workflows to execute without control signal support.
    Pause/Resume/Cancel will not work, but execution proceeds normally.

    TODO: Replace with Redis-backed adapter for production control plane.
    """

    async def get_signal(self, _execution_id: str) -> None:
        """No signals in development mode."""
        return None

    async def send_signal(self, execution_id: str, signal: object) -> None:
        """No-op in development mode."""
        pass

    async def clear_signals(self, execution_id: str) -> None:
        """No-op in development mode."""
        pass


def _get_adapters() -> tuple[ProjectionControlStateAdapter, SignalQueuePort]:
    """Get or create shared adapter instances."""
    global _state_adapter, _signal_adapter

    if _state_adapter is None:
        # Use projection-backed state adapter - reads from event store projections
        _state_adapter = ProjectionControlStateAdapter(get_projection_store())

    if _signal_adapter is None:
        env = os.environ.get("APP_ENVIRONMENT", "")
        if env == "test":
            # Only use in-memory in test environment
            from aef_adapters.control.adapters.memory import InMemorySignalQueueAdapter

            _signal_adapter = InMemorySignalQueueAdapter()
        else:
            # TODO: Use Redis for production. For now, use null adapter.
            _signal_adapter = NullSignalQueueAdapter()

    return _state_adapter, _signal_adapter


@lru_cache(maxsize=1)
def get_controller() -> ExecutionController:
    """Get singleton controller instance.

    State is read from the projection store (backed by event store).
    Signals are queued in-memory (TODO: Redis for production).
    """
    state_adapter, signal_adapter = _get_adapters()

    return ExecutionController(
        state_port=state_adapter,
        signal_port=signal_adapter,
    )


def get_signal_adapter() -> SignalQueuePort:
    """Get the signal adapter for executor integration.

    This is needed so the executor can check for control signals.
    """
    _, signal_adapter = _get_adapters()
    return signal_adapter


def get_state_adapter() -> ProjectionControlStateAdapter:
    """Get the state adapter for executor integration.

    State is read from the projection store (event-sourced).
    """
    state_adapter, _ = _get_adapters()
    return state_adapter
