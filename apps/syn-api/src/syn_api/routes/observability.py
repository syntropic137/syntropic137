"""Observability API endpoints and service operations.

Provides tool timelines and token metrics for sessions.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, HTTPException

from syn_api._wiring import ensure_connected, get_event_store_instance, get_projection_mgr
from syn_api.types import (
    Err,
    ObservabilityError,
    Ok,
    Result,
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
    include_blocked: bool = False,
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
            cost = await manager.session_cost.get_session_cost(session_id)
            if cost is None:
                return Err(
                    ObservabilityError.NOT_FOUND,
                    message=f"Session {session_id} not found",
                )
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

        if execution_id:
            exec_cost = await manager.execution_cost.get_execution_cost(execution_id)
            if exec_cost is None:
                return Err(
                    ObservabilityError.NOT_FOUND,
                    message=f"Execution {execution_id} not found",
                )
            return Ok(
                {
                    "execution_id": execution_id,
                    "input_tokens": exec_cost.input_tokens,
                    "output_tokens": exec_cost.output_tokens,
                    "total_tokens": exec_cost.total_tokens,
                    "total_cost_usd": str(exec_cost.total_cost_usd),
                }
            )

        return Err(
            ObservabilityError.QUERY_FAILED,
            message="Either execution_id or session_id is required",
        )
    except Exception as e:
        return Err(ObservabilityError.QUERY_FAILED, message=str(e))


# =============================================================================
# HTTP Endpoints
# =============================================================================


@router.get("/sessions/{session_id}/tools")
async def get_tool_timeline_endpoint(
    session_id: str,
    limit: int = 100,
    include_blocked: bool = True,
) -> dict:
    """Get tool execution timeline for a session."""
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
    if not timeline:
        raise HTTPException(
            status_code=404,
            detail=f"No tool executions found for session {session_id}",
        )

    return {
        "session_id": session_id,
        "total_executions": len(timeline),
        "executions": timeline,
    }


@router.get("/sessions/{session_id}/tokens")
async def get_token_metrics_endpoint(
    session_id: str,
    include_records: bool = True,  # noqa: ARG001 - kept for API compatibility
) -> dict:
    """Get token usage metrics for a session."""
    result = await get_token_metrics(session_id=session_id)

    if isinstance(result, Err):
        raise HTTPException(
            status_code=404,
            detail=f"No token usage found for session {session_id}",
        )

    return result.value
