"""Projection management for CQRS read models.

IMPORTANT: Events should flow through aggregates and event store only.
Use process_event_envelope() from subscription service, NOT dispatch_event().

Observability projections (TimescaleDB-backed):
- SessionToolsProjection: Tool operations for a session
- SessionCostProjection: Cost metrics (via domain package)

See ADR-026: TimescaleDB for Observability Storage
See ADR-029: Simplified Event System (observability via AgentEventStore)
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
from .session_tools import SessionToolsProjection, ToolOperation

__all__ = [
    "EventProvenance",
    "ProjectionManager",
    "RealTimeProjection",
    "SessionToolsProjection",
    "ToolOperation",
    "get_projection_manager",
    "get_realtime_projection",
    "reset_projection_manager",
    "reset_realtime_projection",
]
