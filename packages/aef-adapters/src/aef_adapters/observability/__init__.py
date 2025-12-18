"""Observability adapters for AEF.

DEPRECATED: This module is being replaced by aef_adapters.events.
The new AgentEventStore provides simpler, higher-throughput event storage.

This module is kept for backwards compatibility during migration.
New code should use:
    from aef_adapters.events import AgentEventStore, EventBuffer
"""

from aef_adapters.observability.protocol import (
    NullObservability,
    ObservabilityPort,
    ObservationContext,
    ObservationType,
)

__all__ = [
    "NullObservability",
    "ObservabilityPort",
    "ObservationContext",
    "ObservationType",
    "get_observability",
]


def get_observability() -> ObservabilityPort:
    """Get the observability adapter.

    Returns a NullObservability instance during migration.
    TODO: Replace with event store integration.
    """
    return NullObservability()


# Stub for legacy code
class AEFSemanticConventions:
    """Stub for semantic conventions during migration."""

    @staticmethod
    def to_resource_attributes(*_args, **_kwargs):
        return {}


def get_collector_endpoint() -> str:
    """Get collector endpoint (deprecated)."""
    return ""
