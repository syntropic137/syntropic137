"""Session API endpoints — thin wrapper over v1."""

from __future__ import annotations

from datetime import (
    datetime,  # noqa: TC003 — Pydantic needs datetime at runtime for model validation
)
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

import syn_api.v1.sessions as sess
from syn_api.types import Err

router = APIRouter(prefix="/sessions", tags=["sessions"])


# =============================================================================
# Response Models
# =============================================================================


class SessionSummaryResponse(BaseModel):
    """Summary of an agent session."""

    id: str
    workflow_id: str | None
    execution_id: str | None = None
    phase_id: str | None
    status: str
    agent_provider: str | None
    total_tokens: int = 0
    total_cost_usd: Decimal = Decimal("0")
    started_at: str | None = None
    completed_at: str | None = None


class OperationInfo(BaseModel):
    """Information about a session operation."""

    operation_id: str
    operation_type: str
    timestamp: datetime | str | None = None
    duration_seconds: float | None = None
    success: bool = True
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    tool_name: str | None = None
    tool_use_id: str | None = None
    tool_input: dict[str, Any] | None = None
    tool_output: str | None = None
    message_role: str | None = None
    message_content: str | None = None
    thinking_content: str | None = None
    git_sha: str | None = None
    git_message: str | None = None
    git_branch: str | None = None
    git_repo: str | None = None


class SessionResponse(BaseModel):
    """Detailed session response."""

    id: str
    workflow_id: str | None
    workflow_name: str | None = None
    execution_id: str | None = None
    phase_id: str | None
    milestone_id: str | None
    agent_provider: str | None
    agent_model: str | None
    status: str
    workspace_path: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    total_cost_usd: Decimal = Decimal("0")
    operations: list[OperationInfo] = Field(default_factory=list)
    started_at: str | None = None
    completed_at: str | None = None
    duration_seconds: float | None = None
    error_message: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


# =============================================================================
# Endpoints
# =============================================================================


@router.get("", response_model=list[SessionSummaryResponse])
async def list_sessions(
    workflow_id: str | None = Query(None, description="Filter by workflow ID"),
    status: str | None = Query(None, description="Filter by status"),
    limit: int = Query(50, ge=1, le=200, description="Max items to return"),
) -> list[SessionSummaryResponse]:
    """List agent sessions with optional filtering."""
    result = await sess.list_sessions(
        workflow_id=workflow_id,
        status=status,
        limit=limit,
    )

    if isinstance(result, Err):
        raise HTTPException(status_code=500, detail=result.message)

    return [
        SessionSummaryResponse(
            id=s.id,
            workflow_id=s.workflow_id,
            execution_id=s.execution_id,
            phase_id=s.phase_id,
            status=s.status,
            agent_provider=s.agent_type,
            total_tokens=s.total_tokens,
            total_cost_usd=Decimal(str(s.total_cost_usd)),
            started_at=str(s.started_at) if s.started_at else None,
            completed_at=str(s.completed_at) if s.completed_at else None,
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
                timestamp=str(op.timestamp) if op.timestamp else None,
                duration_seconds=(op.duration_ms / 1000.0) if op.duration_ms else None,
                success=op.success if op.success is not None else True,
                tool_name=op.tool_name,
                tool_use_id=op.tool_use_id,
                tool_input=tool_input_dict,
                tool_output=op.output_preview,
                git_sha=op.git_sha,
                git_message=op.git_message,
                git_branch=op.git_branch,
                git_repo=op.git_repo,
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
        started_at=str(detail.started_at) if detail.started_at else None,
        completed_at=str(detail.completed_at) if detail.completed_at else None,
        duration_seconds=detail.duration_seconds,
        error_message=None,
        metadata={},
    )
