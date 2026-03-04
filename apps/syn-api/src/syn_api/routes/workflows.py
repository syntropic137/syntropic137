"""Workflow TEMPLATE API endpoints — thin wrapper over v1.

These endpoints manage workflow TEMPLATES (definitions).
For execution details, see /api/executions.
"""

from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

import syn_api.v1.executions as ex
import syn_api.v1.workflows as wf
from syn_api.types import Err

router = APIRouter(prefix="/workflows", tags=["workflows"])


# =============================================================================
# Response Models
# =============================================================================


class WorkflowSummaryResponse(BaseModel):
    """Summary of a workflow TEMPLATE for list views."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    workflow_type: str
    phase_count: int
    created_at: str | None = None
    runs_count: int = 0


class PhaseDefinition(BaseModel):
    """Phase definition within a workflow template."""

    phase_id: str
    name: str
    order: int = 0
    description: str | None = None
    agent_type: str = ""
    prompt_template: str | None = None
    timeout_seconds: int = 300
    allowed_tools: list[str] = Field(default_factory=list)


class WorkflowResponse(BaseModel):
    """Detailed workflow TEMPLATE response."""

    id: str
    name: str
    description: str | None = None
    workflow_type: str
    classification: str
    phases: list[PhaseDefinition] = Field(default_factory=list)
    created_at: str | None = None
    runs_count: int = 0
    runs_link: str | None = None


class WorkflowListResponse(BaseModel):
    """Response for workflow list endpoint."""

    workflows: list[WorkflowSummaryResponse]
    total: int
    page: int = 1
    page_size: int = 20


class ExecutionRunSummary(BaseModel):
    """Summary of a single execution run for list views."""

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
    error_message: str | None = None


class ExecutionRunListResponse(BaseModel):
    """Response for listing workflow execution runs."""

    runs: list[ExecutionRunSummary]
    total: int
    workflow_id: str
    workflow_name: str


class ExecutionHistoryResponse(BaseModel):
    """Response for workflow execution history."""

    workflow_id: str
    workflow_name: str
    executions: list[dict] = Field(default_factory=list)
    total_executions: int = 0


# =============================================================================
# Endpoints
# =============================================================================


@router.get("", response_model=WorkflowListResponse)
async def list_workflows(
    workflow_type: str | None = Query(None, description="Filter by workflow type"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    order_by: str | None = Query(None, description="Sort field (prefix with - for descending)"),
) -> WorkflowListResponse:
    """List all workflow templates."""
    offset = (page - 1) * page_size

    all_result = await wf.list_workflows(
        workflow_type=workflow_type,
        limit=500,
        offset=0,
    )

    if isinstance(all_result, Err):
        raise HTTPException(status_code=500, detail=all_result.message)

    summaries = [
        WorkflowSummaryResponse(
            id=s.id,
            name=s.name,
            workflow_type=s.workflow_type,
            phase_count=s.phase_count,
            created_at=str(s.created_at) if s.created_at else None,
            runs_count=s.runs_count,
        )
        for s in all_result.value
    ]

    # Apply sort order before pagination
    if order_by:
        desc = order_by.startswith("-")
        field = order_by.lstrip("-")
        valid_fields = {"runs_count", "name", "workflow_type", "phase_count", "created_at"}
        if field in valid_fields:
            summaries.sort(key=lambda s: getattr(s, field) or 0, reverse=desc)

    total = len(summaries)
    page_items = summaries[offset : offset + page_size]

    return WorkflowListResponse(
        workflows=page_items,
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{workflow_id}", response_model=WorkflowResponse)
async def get_workflow(workflow_id: str) -> WorkflowResponse:
    """Get workflow details by ID."""
    result = await wf.get_workflow(workflow_id)

    if isinstance(result, Err):
        raise HTTPException(status_code=404, detail=f"Workflow {workflow_id} not found")

    detail = result.value
    phases = []
    for i, p in enumerate(detail.phases or [], 1):
        if isinstance(p, dict):
            phases.append(
                PhaseDefinition(
                    phase_id=str(p.get("id") or p.get("phase_id") or f"phase-{i}"),
                    name=str(p.get("name") or f"Phase {i}"),
                    order=p.get("order", i),
                    description=p.get("description"),
                    agent_type=p.get("agent_type", ""),
                    prompt_template=p.get("prompt_template"),
                    timeout_seconds=p.get("timeout_seconds", 300),
                    allowed_tools=p.get("allowed_tools", []),
                )
            )
        else:
            phases.append(
                PhaseDefinition(
                    phase_id=p.phase_id,
                    name=p.name if hasattr(p, "name") else f"Phase {i}",
                    order=p.order if hasattr(p, "order") else i,
                    description=p.description if hasattr(p, "description") else None,
                    agent_type=p.agent_type if hasattr(p, "agent_type") else "",
                    prompt_template=p.prompt_template if hasattr(p, "prompt_template") else None,
                    timeout_seconds=p.timeout_seconds if hasattr(p, "timeout_seconds") else 300,
                    allowed_tools=list(p.allowed_tools) if hasattr(p, "allowed_tools") else [],
                )
            )

    return WorkflowResponse(
        id=detail.id,
        name=detail.name,
        description=detail.description,
        workflow_type=detail.workflow_type,
        classification=detail.classification,
        phases=phases,
        created_at=str(detail.created_at) if detail.created_at else None,
        runs_count=detail.runs_count,
        runs_link=f"/api/workflows/{detail.id}/runs",
    )


@router.get("/{workflow_id}/runs", response_model=ExecutionRunListResponse)
async def list_workflow_runs(workflow_id: str) -> ExecutionRunListResponse:
    """List all execution runs for a workflow."""
    wf_result = await wf.get_workflow(workflow_id)
    if isinstance(wf_result, Err):
        raise HTTPException(status_code=404, detail=f"Workflow {workflow_id} not found")

    workflow_name = wf_result.value.name

    exec_result = await ex.list_(workflow_id=workflow_id)
    if isinstance(exec_result, Err):
        raise HTTPException(status_code=500, detail=exec_result.message)

    runs = [
        ExecutionRunSummary(
            workflow_execution_id=e.workflow_execution_id,
            workflow_id=e.workflow_id,
            workflow_name=e.workflow_name or workflow_name,
            status=e.status,
            started_at=str(e.started_at) if e.started_at else None,
            completed_at=str(e.completed_at) if e.completed_at else None,
            completed_phases=e.completed_phases,
            total_phases=e.total_phases,
            total_tokens=e.total_tokens,
            total_cost_usd=Decimal(str(e.total_cost_usd)),
            error_message=e.error_message,
        )
        for e in exec_result.value
    ]

    return ExecutionRunListResponse(
        runs=runs,
        total=len(runs),
        workflow_id=workflow_id,
        workflow_name=workflow_name,
    )


@router.get("/{workflow_id}/history", response_model=ExecutionHistoryResponse)
async def get_workflow_history(workflow_id: str) -> ExecutionHistoryResponse:
    """Get execution history for a workflow.

    DEPRECATED: Use /workflows/{workflow_id}/runs instead.
    """
    wf_result = await wf.get_workflow(workflow_id)
    if isinstance(wf_result, Err):
        raise HTTPException(status_code=404, detail=f"Workflow {workflow_id} not found")

    return ExecutionHistoryResponse(
        workflow_id=workflow_id,
        workflow_name=wf_result.value.name,
        executions=[],
        total_executions=0,
    )
