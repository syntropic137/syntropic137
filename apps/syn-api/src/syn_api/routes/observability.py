"""Observability API endpoints and service operations.

Provides tool timelines and token metrics for sessions.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, HTTPException

from syn_api._wiring import ensure_connected, get_projection_mgr
from syn_api.types import (
    Err,
    ObservabilityError,
    Ok,
    Result,
    SessionTokenMetrics,
    ToolTimelineEntry,
    ToolTimelineResponse,
)

if TYPE_CHECKING:
    from syn_api.auth import AuthContext

router = APIRouter(prefix="/observability", tags=["observability"])


# =============================================================================
# Service functions (importable by tests)
# =============================================================================


async def get_tool_timeline(
    session_id: str,
    limit: int = 1000,
    include_blocked: bool = False,  # noqa: ARG001
    auth: AuthContext | None = None,  # noqa: ARG001
) -> Result[list[dict[str, Any]], ObservabilityError]:
    """Get the tool call timeline for a session.

    Args:
        session_id: The session to get the timeline for.
        limit: Maximum events to return.
        include_blocked: Include blocked tool calls.
        auth: Optional authentication context.

    Returns:
        Ok(list[dict]) with timeline events on success.
    """
    await ensure_connected()
    try:
        manager = get_projection_mgr()
        projection = manager.session_tools
        operations = await projection.get(session_id)

        result = []
        for op in (operations or [])[:limit]:
            result.append(
                {
                    "observation_id": op.observation_id,
                    "operation_type": op.operation_type,
                    "tool_name": op.tool_name,
                    "timestamp": str(op.timestamp),
                    "duration_ms": op.duration_ms,
                    "success": op.success,
                }
            )
        return Ok(result)
    except Exception as e:
        return Err(ObservabilityError.QUERY_FAILED, message=str(e))


async def _get_session_token_metrics(
    manager: Any,  # noqa: ANN401
    session_id: str,
) -> Result[dict[str, Any], ObservabilityError]:
    """Build token metrics dict for a single session."""
    cost = await manager.session_cost.get_session_cost(session_id)
    if cost is None:
        return Err(ObservabilityError.NOT_FOUND, message=f"Session {session_id} not found")
    return Ok(
        {
            "session_id": session_id,
            "input_tokens": cost.input_tokens,
            "output_tokens": cost.output_tokens,
            "total_tokens": cost.total_tokens,
            "total_cost_usd": str(cost.total_cost_usd),
            "cache_creation_tokens": cost.cache_creation_tokens,
            "cache_read_tokens": cost.cache_read_tokens,
        }
    )


async def _get_execution_token_metrics(
    manager: Any,  # noqa: ANN401
    execution_id: str,
) -> Result[dict[str, Any], ObservabilityError]:
    """Build token metrics dict for a single execution."""
    exec_cost = await manager.execution_cost.get_execution_cost(execution_id)
    if exec_cost is None:
        return Err(ObservabilityError.NOT_FOUND, message=f"Execution {execution_id} not found")
    return Ok(
        {
            "execution_id": execution_id,
            "input_tokens": exec_cost.input_tokens,
            "output_tokens": exec_cost.output_tokens,
            "total_tokens": exec_cost.total_tokens,
            "total_cost_usd": str(exec_cost.total_cost_usd),
        }
    )


async def get_token_metrics(
    execution_id: str | None = None,
    session_id: str | None = None,
    auth: AuthContext | None = None,  # noqa: ARG001
) -> Result[dict[str, Any], ObservabilityError]:
    """Get token usage metrics for an execution or session.

    Args:
        execution_id: Filter by execution ID.
        session_id: Filter by session ID.
        auth: Optional authentication context.

    Returns:
        Ok(dict) with token metrics on success.
    """
    await ensure_connected()
    try:
        manager = get_projection_mgr()

        if session_id:
            return await _get_session_token_metrics(manager, session_id)

        if execution_id:
            return await _get_execution_token_metrics(manager, execution_id)

        return Err(
            ObservabilityError.QUERY_FAILED,
            message="Either execution_id or session_id is required",
        )
    except Exception as e:
        return Err(ObservabilityError.QUERY_FAILED, message=str(e))


# =============================================================================
# HTTP Endpoints
# =============================================================================


@router.get("/sessions/{session_id}/tools", response_model=ToolTimelineResponse)
async def get_tool_timeline_endpoint(
    session_id: str,
    limit: int = 100,
    include_blocked: bool = True,
) -> ToolTimelineResponse:
    """Get tool execution timeline for a session."""
    from syn_api.prefix_resolver import resolve_or_raise

    mgr = get_projection_mgr()
    session_id = await resolve_or_raise(mgr.store, "session_summaries", session_id, "Session")
    result = await get_tool_timeline(
        session_id=session_id,
        limit=limit,
        include_blocked=include_blocked,
    )

    if isinstance(result, Err):
        raise HTTPException(
            status_code=404,
            detail=f"No tool executions found for session {session_id}",
        )

    timeline = result.value

    return ToolTimelineResponse(
        session_id=session_id,
        total_executions=len(timeline),
        executions=[
            ToolTimelineEntry(
                observation_id=t.get("observation_id", ""),
                operation_type=t.get("operation_type", ""),
                tool_name=t.get("tool_name"),
                timestamp=t.get("timestamp"),
                duration_ms=t.get("duration_ms"),
                success=t.get("success"),
            )
            for t in timeline
        ],
    )


@router.get("/sessions/{session_id}/tokens", response_model=SessionTokenMetrics)
async def get_token_metrics_endpoint(
    session_id: str,
    include_records: bool = True,  # noqa: ARG001 - kept for API compatibility
) -> SessionTokenMetrics:
    """Get token usage metrics for a session."""
    from syn_api.prefix_resolver import resolve_or_raise

    mgr = get_projection_mgr()
    session_id = await resolve_or_raise(mgr.store, "session_summaries", session_id, "Session")
    result = await get_token_metrics(session_id=session_id)

    if isinstance(result, Err):
        raise HTTPException(
            status_code=404,
            detail=f"No token usage found for session {session_id}",
        )

    data = result.value
    return SessionTokenMetrics(
        session_id=data.get("session_id", session_id),
        input_tokens=data.get("input_tokens", 0),
        output_tokens=data.get("output_tokens", 0),
        total_tokens=data.get("total_tokens", 0),
        total_cost_usd=data.get("total_cost_usd", "0"),
        cache_creation_tokens=data.get("cache_creation_tokens", 0),
        cache_read_tokens=data.get("cache_read_tokens", 0),
    )
