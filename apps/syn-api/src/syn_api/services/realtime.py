"""Realtime operations — access the RealTimeProjection for SSE support.

The SSE protocol layer lives in ``syn_api.routes.sse``; this module
provides the service-layer access point to the projection singleton.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syn_api._wiring import get_realtime
from syn_api.types import ObservabilityError, Ok, RealtimeHealth, Result

if TYPE_CHECKING:
    from syn_adapters.projections.realtime import RealTimeProjection
    from syn_api.auth import AuthContext


def get_realtime_projection_ref() -> RealTimeProjection:
    """Return the RealTimeProjection singleton.

    The SSE route handlers use this to connect/disconnect subscribers
    and receive broadcast frames via their per-client queues.
    """
    return get_realtime()  # type: ignore[return-value]


async def get_realtime_health(
    auth: AuthContext | None = None,
) -> Result[RealtimeHealth, ObservabilityError]:
    """Get health status of the realtime SSE projection.

    Args:
        auth: Optional authentication context.

    Returns:
        Ok(RealtimeHealth) with active subscriber and execution counts.
    """
    projection = get_realtime()
    return Ok(
        RealtimeHealth(
            active_executions=projection.execution_count,
            active_connections=projection.connection_count,
        )
    )
