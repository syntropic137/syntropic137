"""Observability API endpoints for tool and token metrics.

These endpoints expose data from observation events (Pattern 2: Event Log + CQRS).
See ADR-018 for architectural rationale.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from aef_adapters.projections import get_projection_manager
from aef_domain.contexts.agent_sessions.domain.queries import (
    GetToolTimelineQuery,
)
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
    include_records: bool = True,  # noqa: ARG001 - kept for API compatibility
) -> dict:
    """Get token usage metrics for a session.

    Args:
        session_id: The session to get token metrics for.
        include_records: Whether to include individual token records (deprecated).

    Returns:
        Token metrics with aggregated data from session_cost projection.
    """
    manager = get_projection_manager()
    session_cost = await manager.session_cost.get_session_cost(session_id)

    if session_cost is None or (
        session_cost.input_tokens == 0 and session_cost.output_tokens == 0
    ):
        raise HTTPException(
            status_code=404,
            detail=f"No token usage found for session {session_id}",
        )

    return {
        "session_id": session_id,
        "input_tokens": session_cost.input_tokens,
        "output_tokens": session_cost.output_tokens,
        "cache_read_tokens": session_cost.cache_read_tokens,
        "cache_creation_tokens": session_cost.cache_creation_tokens,
        "total_cost_usd": float(session_cost.total_cost_usd),
        "turns": session_cost.turns,
    }
