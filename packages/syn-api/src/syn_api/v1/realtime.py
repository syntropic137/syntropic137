"""Realtime operations — access the RealTimeProjection for WebSocket support.

The WebSocket protocol stays in the dashboard — the API module just
provides access to the projection singleton.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from syn_api._wiring import get_realtime
from syn_api.types import ObservabilityError, Ok, RealtimeHealth, Result

if TYPE_CHECKING:
    from syn_api.auth import AuthContext


def get_realtime_projection_ref() -> Any:
    """Return the RealTimeProjection singleton.

    The dashboard's WebSocket handler uses this to connect/disconnect
    clients and broadcast events.
    """
    return get_realtime()


async def get_realtime_health(
    auth: AuthContext | None = None,  # noqa: ARG001
) -> Result[RealtimeHealth, ObservabilityError]:
    """Get health status of the realtime projection.

    Args:
        auth: Optional authentication context.

    Returns:
        Ok(RealtimeHealth) with connection and execution counts.
    """
    projection = get_realtime()
    return Ok(
        RealtimeHealth(
            active_executions=getattr(projection, "execution_count", 0),
            active_connections=getattr(projection, "connection_count", 0),
        )
    )
