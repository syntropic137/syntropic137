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

__all__ = [
    "EventProvenance",
    "ProjectionManager",
    "get_projection_manager",
    "reset_projection_manager",
]
