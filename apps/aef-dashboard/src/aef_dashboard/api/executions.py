"""Execution API endpoints.

Provides endpoints for accessing workflow execution (run) details.
"""

from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from aef_adapters.projections import get_projection_manager

router = APIRouter(prefix="/executions", tags=["executions"])


# =============================================================================
# Response Models
# =============================================================================


class PhaseExecutionInfo(BaseModel):
    """Information about a phase execution within a run."""

    phase_id: str
    name: str
    status: str
    session_id: str | None = None
    artifact_id: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    duration_seconds: float = 0.0
    cost_usd: Decimal = Decimal("0")
    started_at: str | None = None
    completed_at: str | None = None
    error_message: str | None = None


class ExecutionDetailResponse(BaseModel):
    """Detailed response for a workflow execution run."""

    execution_id: str
    workflow_id: str
    workflow_name: str
    status: str
    started_at: str | None = None
    completed_at: str | None = None
    phases: list[PhaseExecutionInfo] = Field(default_factory=list)
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_tokens: int = 0
    total_cost_usd: Decimal = Decimal("0")
    total_duration_seconds: float = 0.0
    artifact_ids: list[str] = Field(default_factory=list)
    error_message: str | None = None


# =============================================================================
# Endpoints
# =============================================================================


@router.get("/{execution_id}", response_model=ExecutionDetailResponse)
async def get_execution(execution_id: str) -> ExecutionDetailResponse:
    """Get detailed information about a workflow execution run.

    Returns phase-level metrics for the execution, including token usage,
    duration, and cost for each phase.
    """
    manager = get_projection_manager()
    detail = await manager.execution_detail.get_by_id(execution_id)

    if detail is None:
        raise HTTPException(
            status_code=404,
            detail=f"Execution {execution_id} not found",
        )

    # Convert phases
    phases = [
        PhaseExecutionInfo(
            phase_id=p.phase_id,
            name=p.name,
            status=p.status,
            session_id=p.session_id,
            artifact_id=p.artifact_id,
            input_tokens=p.input_tokens,
            output_tokens=p.output_tokens,
            total_tokens=p.total_tokens,
            duration_seconds=p.duration_seconds,
            cost_usd=Decimal(str(p.cost_usd)),
            started_at=str(p.started_at) if p.started_at else None,
            completed_at=str(p.completed_at) if p.completed_at else None,
            error_message=p.error_message,
        )
        for p in detail.phases
    ]

    return ExecutionDetailResponse(
        execution_id=detail.execution_id,
        workflow_id=detail.workflow_id,
        workflow_name=detail.workflow_name,
        status=detail.status,
        started_at=str(detail.started_at) if detail.started_at else None,
        completed_at=str(detail.completed_at) if detail.completed_at else None,
        phases=phases,
        total_input_tokens=detail.total_input_tokens,
        total_output_tokens=detail.total_output_tokens,
        total_tokens=detail.total_input_tokens + detail.total_output_tokens,
        total_cost_usd=Decimal(str(detail.total_cost_usd)),
        total_duration_seconds=detail.total_duration_seconds,
        artifact_ids=list(detail.artifact_ids),
        error_message=detail.error_message,
    )
