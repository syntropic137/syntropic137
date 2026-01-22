"""Domain layer for observability context.

Exports:
- AgentObservationEvent: Unified telemetry event for all agent activities
- ObservationType: Classification of observation types
"""

from aef_domain.contexts.observability.events import (
    AgentObservationEvent,
    ObservationType,
)

__all__ = [
    "AgentObservationEvent",
    "ObservationType",
]
