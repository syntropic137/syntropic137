"""Projection management for CQRS read models.

IMPORTANT: Events should flow through aggregates and event store only.
Use process_event_envelope() from subscription service, NOT dispatch_event().

Observability projections (TimescaleDB-backed):
- SessionToolsProjection: Tool operations for a session
- SessionCostProjection: Cost metrics (via domain package)

See ADR-026: TimescaleDB for Observability Storage
"""

from .manager import (
    EventProvenance,
    ProjectionManager,
    get_projection_manager,
    reset_projection_manager,
)
from .observability_base import ObservabilityProjection
from .realtime import (
    RealTimeProjection,
    get_realtime_projection,
    reset_realtime_projection,
)
from .session_tools import SessionToolsProjection, ToolOperation

__all__ = [
    "EventProvenance",
    "ObservabilityProjection",
    "ProjectionManager",
    "RealTimeProjection",
    "SessionToolsProjection",
    "ToolOperation",
    "get_projection_manager",
    "get_realtime_projection",
    "reset_projection_manager",
    "reset_realtime_projection",
]
