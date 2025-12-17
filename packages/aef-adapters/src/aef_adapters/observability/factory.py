"""Factory for creating ObservabilityPort implementations (legacy).

DEPRECATED: This module uses the legacy ObservabilityPort protocol.
New code should use OTel-first observability with create_phase_otel_config().

Usage (legacy):
    from aef_adapters.observability import get_observability

    # Get the singleton adapter
    observability = get_observability()

    # Pass to executors
    executor = WorkflowExecutor(observability=observability)

Usage (recommended):
    from aef_adapters.observability import create_phase_otel_config

    otel_config = create_phase_otel_config(...)
    env = otel_config.to_env()  # Inject into container
"""

from __future__ import annotations

import warnings
from typing import TYPE_CHECKING

from aef_adapters.observability.timescale import TimescaleObservability
from aef_adapters.storage.observability_writer import (
    ObservabilityWriter,
    get_observability_writer,
)

if TYPE_CHECKING:
    from aef_adapters.observability.protocol import ObservabilityPort

# Singleton instance
_observability_adapter: TimescaleObservability | None = None


def get_observability(
    connection_string: str | None = None,
    *,
    writer: ObservabilityWriter | None = None,
) -> ObservabilityPort:
    """Get or create the ObservabilityPort singleton.

    DEPRECATED: Use create_phase_otel_config() for OTel-first observability.

    This legacy function handles connection configuration and singleton management
    for the TimescaleDB observability adapter.

    Args:
        connection_string: Optional TimescaleDB connection string.
            If not provided, uses settings from environment.
        writer: Optional pre-configured ObservabilityWriter.
            If provided, uses this instead of creating a new one.

    Returns:
        ObservabilityPort implementation (TimescaleObservability)

    Example (legacy):
        from aef_adapters.observability import get_observability

        observability = get_observability()
        executor = WorkflowExecutor(observability=observability)

    Example (recommended):
        from aef_adapters.observability import create_phase_otel_config

        otel_config = create_phase_otel_config(...)
        env = otel_config.to_env()
    """
    warnings.warn(
        "get_observability() is deprecated. Use create_phase_otel_config() "
        "for OTel-first observability.",
        DeprecationWarning,
        stacklevel=2,
    )
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
