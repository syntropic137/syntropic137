"""Workflow API endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from aef_dashboard.models.schemas import (
    ExecutionHistoryResponse,
    PhaseInfo,
    WorkflowListResponse,
    WorkflowResponse,
    WorkflowSummary,
)
from aef_dashboard.read_models import (
    WorkflowReadModel,
    get_all_workflows,
    get_workflow_by_id,
)

router = APIRouter(prefix="/workflows", tags=["workflows"])


def _workflow_to_summary(workflow: WorkflowReadModel) -> WorkflowSummary:
    """Convert a WorkflowReadModel to a WorkflowSummary."""
    return WorkflowSummary(
        id=workflow.id,
        name=workflow.name,
        workflow_type=workflow.workflow_type,
        status=workflow.status,
        phase_count=len(workflow.phases),
        created_at=workflow.created_at,
    )


def _workflow_to_response(workflow: WorkflowReadModel) -> WorkflowResponse:
    """Convert a WorkflowReadModel to a WorkflowResponse."""
    phases = [
        PhaseInfo(
            phase_id=p.get("phase_id", f"phase-{i}"),
            name=p.get("name", f"Phase {i}"),
            order=p.get("order", i),
            description=p.get("description"),
        )
        for i, p in enumerate(workflow.phases, 1)
    ]

    return WorkflowResponse(
        id=workflow.id,
        name=workflow.name,
        description=workflow.description,
        workflow_type=workflow.workflow_type,
        classification=workflow.classification,
        status=workflow.status,
        phases=phases,
        created_at=workflow.created_at,
        updated_at=None,
        metadata={},
    )


@router.get("", response_model=WorkflowListResponse)
async def list_workflows(
    status: str | None = Query(None, description="Filter by status"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
) -> WorkflowListResponse:
    """List all workflows with optional filtering."""
    all_workflows = await get_all_workflows()

    # Filter by status if provided
    if status:
        all_workflows = [w for w in all_workflows if w.status == status]

    total = len(all_workflows)

    # Apply pagination
    start = (page - 1) * page_size
    end = start + page_size
    paginated = all_workflows[start:end]

    return WorkflowListResponse(
        workflows=[_workflow_to_summary(w) for w in paginated],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{workflow_id}", response_model=WorkflowResponse)
async def get_workflow(workflow_id: str) -> WorkflowResponse:
    """Get workflow details by ID."""
    workflow = await get_workflow_by_id(workflow_id)

    if workflow is None:
        raise HTTPException(status_code=404, detail=f"Workflow {workflow_id} not found")

    return _workflow_to_response(workflow)


@router.get("/{workflow_id}/history", response_model=ExecutionHistoryResponse)
async def get_workflow_history(workflow_id: str) -> ExecutionHistoryResponse:
    """Get execution history for a workflow."""
    workflow = await get_workflow_by_id(workflow_id)

    if workflow is None:
        raise HTTPException(status_code=404, detail=f"Workflow {workflow_id} not found")

    # For now, return empty history (sessions/artifacts not yet implemented)
    return ExecutionHistoryResponse(
        workflow_id=workflow_id,
        workflow_name=workflow.name,
        executions=[],
        total_executions=0,
    )
