"""Factory for creating ObservabilityPort implementations.

This module provides a factory function that creates the appropriate
observability adapter based on the environment and configuration.

Usage:
    from aef_adapters.observability import get_observability

    # Get the singleton adapter
    observability = get_observability()

    # Pass to executors
    executor = WorkflowExecutor(observability=observability)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from aef_adapters.observability.timescale import TimescaleObservability
from aef_adapters.storage.observability_writer import (
    ObservabilityWriter,
    get_observability_writer,
)

if TYPE_CHECKING:
    from agentic_observability import ObservabilityPort

# Singleton instance
_observability_adapter: TimescaleObservability | None = None


def get_observability(
    connection_string: str | None = None,
    *,
    writer: ObservabilityWriter | None = None,
) -> ObservabilityPort:
    """Get or create the ObservabilityPort singleton.

    This is the recommended way to obtain an observability adapter.
    It handles connection configuration and singleton management.

    Args:
        connection_string: Optional TimescaleDB connection string.
            If not provided, uses settings from environment.
        writer: Optional pre-configured ObservabilityWriter.
            If provided, uses this instead of creating a new one.

    Returns:
        ObservabilityPort implementation (TimescaleObservability)

    Example:
        from aef_adapters.observability import get_observability

        observability = get_observability()
        executor = WorkflowExecutor(observability=observability)
    """
    global _observability_adapter

    if _observability_adapter is None:
        if writer is None:
            writer = get_observability_writer(connection_string)

        _observability_adapter = TimescaleObservability(writer)

    return _observability_adapter


async def reset_observability() -> None:
    """Reset the singleton (for testing).

    This closes any existing connections and clears the singleton,
    allowing a fresh instance to be created.
    """
    global _observability_adapter

    if _observability_adapter is not None:
        await _observability_adapter.close()
        _observability_adapter = None
