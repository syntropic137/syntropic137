"""Projection management for CQRS read models.

IMPORTANT: Events should flow through aggregates and event store only.
Use process_event_envelope() from subscription service, NOT dispatch_event().
"""

from .manager import (
    EventProvenance,
    ProjectionManager,
    get_projection_manager,
    reset_projection_manager,
)
from .realtime import (
    RealTimeProjection,
    get_realtime_projection,
    reset_realtime_projection,
)

__all__ = [
    "EventProvenance",
    "ProjectionManager",
    "RealTimeProjection",
    "get_projection_manager",
    "get_realtime_projection",
    "reset_projection_manager",
    "reset_realtime_projection",
]
