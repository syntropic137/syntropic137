"""Execution API endpoints — thin wrapper over syn_api."""

from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

import syn_api.v1.executions as ex
from syn_api.types import Err

router = APIRouter(prefix="/executions", tags=["executions"])


# =============================================================================
# Response Models
# =============================================================================


class PhaseOperationInfo(BaseModel):
    """Information about an operation within a phase."""

    operation_id: str
    operation_type: str
    timestamp: str | None = None
    tool_name: str | None = None
    tool_use_id: str | None = None
    success: bool = True


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
    operations: list[PhaseOperationInfo] = []


class ExecutionDetailResponse(BaseModel):
    """Detailed response for a workflow execution run."""

    workflow_execution_id: str
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


class ExecutionSummaryResponse(BaseModel):
    """Summary of a workflow execution for list views."""

    workflow_execution_id: str
    workflow_id: str
    workflow_name: str
    status: str
    started_at: str | None = None
    completed_at: str | None = None
    completed_phases: int = 0
    total_phases: int = 0
    total_tokens: int = 0
    total_cost_usd: Decimal = Decimal("0")
    tool_call_count: int = 0


class ExecutionListResponse(BaseModel):
    """Response for listing all executions."""

    executions: list[ExecutionSummaryResponse]
    total: int
    page: int = 1
    page_size: int = 50


# =============================================================================
# Endpoints
# =============================================================================


@router.get("", response_model=ExecutionListResponse)
async def list_all_executions(
    status: str | None = Query(None, description="Filter by status"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(50, ge=1, le=100, description="Items per page"),
) -> ExecutionListResponse:
    """List all workflow executions across all workflows."""
    offset = (page - 1) * page_size
    result = await ex.list_(status=status, limit=page_size, offset=offset)

    if isinstance(result, Err):
        raise HTTPException(status_code=500, detail=result.message)

    def _to_str(val: object | None) -> str | None:
        return str(val) if val is not None else None

    return ExecutionListResponse(
        executions=[
            ExecutionSummaryResponse(
                workflow_execution_id=e.workflow_execution_id,
                workflow_id=e.workflow_id,
                workflow_name=e.workflow_name,
                status=e.status,
                started_at=_to_str(e.started_at),
                completed_at=_to_str(e.completed_at),
                completed_phases=e.completed_phases,
                total_phases=e.total_phases,
                total_tokens=e.total_tokens,
                total_cost_usd=Decimal(str(e.total_cost_usd)),
                tool_call_count=e.tool_call_count,
            )
            for e in result.value
        ],
        total=len(result.value),
        page=page,
        page_size=page_size,
    )


@router.get("/{execution_id}", response_model=ExecutionDetailResponse)
async def get_execution(execution_id: str) -> ExecutionDetailResponse:
    """Get detailed information about a workflow execution run."""
    result = await ex.get_detail(execution_id)

    if isinstance(result, Err):
        raise HTTPException(status_code=404, detail=f"Execution {execution_id} not found")

    detail = result.value
    phases = []
    for p in detail.phases or []:
        operations = [
            PhaseOperationInfo(
                operation_id=op.observation_id,
                operation_type=op.operation_type,
                timestamp=str(op.timestamp) if op.timestamp else None,
                tool_name=op.tool_name,
                tool_use_id=op.tool_use_id,
                success=op.success if op.success is not None else True,
            )
            for op in (p.operations or [])
        ]
        phases.append(
            PhaseExecutionInfo(
                phase_id=p.phase_id,
                name=p.name,
                status=p.status,
                session_id=p.session_id,
                artifact_id=p.artifact_id,
                input_tokens=p.input_tokens,
                output_tokens=p.output_tokens,
                total_tokens=p.input_tokens + p.output_tokens,
                duration_seconds=p.duration_seconds or 0.0,
                cost_usd=Decimal(str(p.cost_usd)),
                started_at=str(p.started_at) if p.started_at else None,
                completed_at=str(p.completed_at) if p.completed_at else None,
                operations=operations,
            )
        )

    total_input = sum(p.input_tokens for p in detail.phases or [])
    total_output = sum(p.output_tokens for p in detail.phases or [])
    artifact_ids = [p.artifact_id for p in phases if p.artifact_id]

    return ExecutionDetailResponse(
        workflow_execution_id=detail.workflow_execution_id,
        workflow_id=detail.workflow_id,
        workflow_name=detail.workflow_name,
        status=detail.status,
        started_at=str(detail.started_at) if detail.started_at else None,
        completed_at=str(detail.completed_at) if detail.completed_at else None,
        phases=phases,
        total_input_tokens=total_input,
        total_output_tokens=total_output,
        total_tokens=detail.total_tokens,
        total_cost_usd=Decimal(str(detail.total_cost_usd)),
        artifact_ids=artifact_ids,
        error_message=detail.error_message,
    )
