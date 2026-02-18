"""Observability API endpoints — thin wrapper over syn_api."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

import syn_api.v1.observability as obs
from syn_api.types import Err

router = APIRouter(prefix="/observability", tags=["observability"])


@router.get("/sessions/{session_id}/tools")
async def get_tool_timeline(
    session_id: str,
    limit: int = 100,
    include_blocked: bool = True,
) -> dict:
    """Get tool execution timeline for a session."""
    result = await obs.get_tool_timeline(
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
async def get_token_metrics(
    session_id: str,
    include_records: bool = True,  # noqa: ARG001 - kept for API compatibility
) -> dict:
    """Get token usage metrics for a session."""
    result = await obs.get_token_metrics(session_id=session_id)

    if isinstance(result, Err):
        raise HTTPException(
            status_code=404,
            detail=f"No token usage found for session {session_id}",
        )

    return result.value
