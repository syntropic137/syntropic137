"""Control plane service factory."""

from __future__ import annotations

from functools import lru_cache

from aef_adapters.control import ExecutionController
from aef_adapters.control.adapters.memory import (
    InMemoryControlStateAdapter,
    InMemorySignalQueueAdapter,
)

# Global adapter instances (shared across controller instances)
_state_adapter: InMemoryControlStateAdapter | None = None
_signal_adapter: InMemorySignalQueueAdapter | None = None


def _get_adapters() -> tuple[InMemoryControlStateAdapter, InMemorySignalQueueAdapter]:
    """Get or create shared adapter instances."""
    global _state_adapter, _signal_adapter

    if _state_adapter is None:
        _state_adapter = InMemoryControlStateAdapter()
    if _signal_adapter is None:
        _signal_adapter = InMemorySignalQueueAdapter()

    return _state_adapter, _signal_adapter


@lru_cache(maxsize=1)
def get_controller() -> ExecutionController:
    """Get singleton controller instance.

    For development, uses in-memory adapters.
    TODO: Use Redis adapters in production for distributed state.
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


def get_state_adapter() -> InMemoryControlStateAdapter:
    """Get the state adapter for executor integration.

    This is needed so the executor can update state on transitions.
    """
    state_adapter, _ = _get_adapters()
    return state_adapter
