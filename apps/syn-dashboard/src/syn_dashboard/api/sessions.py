"""Session API endpoints — thin wrapper over syn_api."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from fastapi import APIRouter, HTTPException, Query

import syn_api.v1.sessions as sess
from syn_api.types import Err
from syn_dashboard.models.schemas import (
    OperationInfo,
    SessionResponse,
    SessionSummary,
)

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.get("", response_model=list[SessionSummary])
async def list_sessions(
    workflow_id: str | None = Query(None, description="Filter by workflow ID"),
    status: str | None = Query(None, description="Filter by status"),
    limit: int = Query(50, ge=1, le=200, description="Max items to return"),
) -> list[SessionSummary]:
    """List agent sessions with optional filtering."""
    result = await sess.list_sessions(
        workflow_id=workflow_id,
        status=status,
        limit=limit,
    )

    if isinstance(result, Err):
        raise HTTPException(status_code=500, detail=result.message)

    return [
        SessionSummary(
            id=s.id,
            workflow_id=s.workflow_id,
            execution_id=s.execution_id,
            phase_id=s.phase_id,
            status=s.status,
            agent_provider=s.agent_type,
            total_tokens=s.total_tokens,
            total_cost_usd=Decimal(str(s.total_cost_usd)),
            started_at=s.started_at,
            completed_at=s.completed_at,
        )
        for s in result.value
    ]


@router.get("/{session_id}", response_model=SessionResponse)
async def get_session(session_id: str) -> SessionResponse:
    """Get session details by ID."""
    result = await sess.get_session(session_id)

    if isinstance(result, Err):
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    detail = result.value

    # Convert tool operations to API format
    operations: list[OperationInfo] = []
    for op in detail.operations or []:
        # Parse tool input if available
        tool_input_dict: dict[str, Any] | None = None
        input_preview = op.input_preview
        if input_preview:
            import json

            try:
                parsed = json.loads(input_preview)
                tool_input_dict = parsed if isinstance(parsed, dict) else {"raw": input_preview}
            except (json.JSONDecodeError, TypeError):
                tool_input_dict = {"raw": input_preview}

        operations.append(
            OperationInfo(
                operation_id=op.observation_id,
                operation_type=op.operation_type,
                timestamp=op.timestamp,
                duration_seconds=(op.duration_ms / 1000.0) if op.duration_ms else None,
                success=op.success if op.success is not None else True,
                tool_name=op.tool_name,
                tool_use_id=op.tool_use_id,
                tool_input=tool_input_dict,
                tool_output=op.output_preview,
            )
        )

    return SessionResponse(
        id=detail.id,
        workflow_id=detail.workflow_id,
        workflow_name=detail.workflow_name,
        execution_id=detail.execution_id,
        phase_id=detail.phase_id,
        milestone_id=None,
        agent_provider=detail.agent_type,
        agent_model=None,
        status=detail.status,
        workspace_path=detail.workspace_path,
        input_tokens=detail.input_tokens,
        output_tokens=detail.output_tokens,
        total_tokens=detail.total_tokens,
        total_cost_usd=Decimal(str(detail.total_cost_usd)),
        operations=operations,
        started_at=detail.started_at,
        completed_at=detail.completed_at,
        duration_seconds=detail.duration_seconds,
        error_message=None,
        metadata={},
    )
