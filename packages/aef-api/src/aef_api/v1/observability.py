"""Observability operations — token metrics and tool timelines.

Provides access to execution telemetry and cost tracking data.

Stub implementation for Phase 1 — complete signatures and types,
with TODO markers pointing to domain slices.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from aef_api.types import Err, ObservabilityError, Result

if TYPE_CHECKING:
    from aef_api.auth import AuthContext


async def get_token_metrics(
    execution_id: str | None = None,
    session_id: str | None = None,
    auth: AuthContext | None = None,
) -> Result[dict[str, Any], ObservabilityError]:
    """Get token usage metrics for an execution or session.

    Args:
        execution_id: Filter by execution ID.
        session_id: Filter by session ID.
        auth: Optional authentication context.

    Returns:
        Ok(dict) with token metrics on success, Err(ObservabilityError) on failure.
    """
    # TODO(#92): Implement — maps to domain projections for cost/token tracking
    # Wire: get_projection_manager().session_cost / execution_cost
    return Err(
        ObservabilityError.NOT_IMPLEMENTED,
        message="get_token_metrics not yet implemented — see #92 Phase 1",
    )


async def get_tool_timeline(
    session_id: str,
    auth: AuthContext | None = None,
) -> Result[list[dict[str, Any]], ObservabilityError]:
    """Get the tool call timeline for a session.

    Args:
        session_id: The session to get the timeline for.
        auth: Optional authentication context.

    Returns:
        Ok(list[dict]) with timeline events on success, Err(ObservabilityError) on failure.
    """
    # TODO(#92): Implement — maps to ToolTimelineProjection
    # Wire: get_projection_manager().tool_timeline
    return Err(
        ObservabilityError.NOT_IMPLEMENTED,
        message="get_tool_timeline not yet implemented — see #92 Phase 1",
    )
