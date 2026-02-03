"""Observability API endpoints for tool and token metrics.

These endpoints expose data from observation events (Pattern 2: Event Log + CQRS).
See ADR-018 for architectural rationale.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from aef_adapters.projections import get_projection_manager
from aef_domain.contexts.agent_sessions.domain.queries import (
    GetTokenMetricsQuery,
    GetToolTimelineQuery,
)
from aef_domain.contexts.agent_sessions.slices.token_metrics import TokenMetricsHandler
from aef_domain.contexts.agent_sessions.slices.tool_timeline import ToolTimelineHandler

router = APIRouter(prefix="/observability", tags=["observability"])


@router.get("/sessions/{session_id}/tools")
async def get_tool_timeline(
    session_id: str,
    limit: int = 100,
    include_blocked: bool = True,
) -> dict:
    """Get tool execution timeline for a session.

    Args:
        session_id: The session to get tool timeline for.
        limit: Maximum number of executions to return.
        include_blocked: Whether to include blocked tool executions.

    Returns:
        Tool timeline with execution details.
    """
    manager = get_projection_manager()
    handler = ToolTimelineHandler(manager.tool_timeline)

    query = GetToolTimelineQuery(
        session_id=session_id,
        limit=limit,
        include_blocked=include_blocked,
    )
    timeline = await handler.handle(query)

    if timeline.total_executions == 0:
        raise HTTPException(
            status_code=404,
            detail=f"No tool executions found for session {session_id}",
        )

    return timeline.to_dict()


@router.get("/sessions/{session_id}/tokens")
async def get_token_metrics(
    session_id: str,
    include_records: bool = True,
) -> dict:
    """Get token usage metrics for a session.

    Args:
        session_id: The session to get token metrics for.
        include_records: Whether to include individual token records.

    Returns:
        Token metrics with aggregated and per-message data.
    """
    manager = get_projection_manager()
    handler = TokenMetricsHandler(manager.token_metrics)

    query = GetTokenMetricsQuery(
        session_id=session_id,
        include_records=include_records,
    )
    metrics = await handler.handle(query)

    if metrics.message_count == 0:
        raise HTTPException(
            status_code=404,
            detail=f"No token usage found for session {session_id}",
        )

    return metrics.to_dict()
