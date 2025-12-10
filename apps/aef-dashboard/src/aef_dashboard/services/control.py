"""Control plane service factory."""

from __future__ import annotations

from functools import lru_cache

from aef_adapters.control import ExecutionController
from aef_adapters.control.adapters.memory import InMemorySignalQueueAdapter
from aef_adapters.control.adapters.projection import ProjectionControlStateAdapter
from aef_adapters.projection_stores import get_projection_store

# Global adapter instances (shared across controller instances)
_state_adapter: ProjectionControlStateAdapter | None = None
_signal_adapter: InMemorySignalQueueAdapter | None = None


def _get_adapters() -> tuple[ProjectionControlStateAdapter, InMemorySignalQueueAdapter]:
    """Get or create shared adapter instances."""
    global _state_adapter, _signal_adapter

    if _state_adapter is None:
        # Use projection-backed state adapter - reads from event store projections
        _state_adapter = ProjectionControlStateAdapter(get_projection_store())
    if _signal_adapter is None:
        # Signal queue is still in-memory for now
        # TODO: Use Redis for distributed signal delivery in production
        _signal_adapter = InMemorySignalQueueAdapter()

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


def get_signal_adapter() -> InMemorySignalQueueAdapter:
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
