"""Workflow API endpoints."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException, Query

from aef_adapters.projections import get_projection_manager
from aef_dashboard.models.schemas import (
    ExecutionHistoryResponse,
    PhaseInfo,
    WorkflowListResponse,
    WorkflowResponse,
    WorkflowSummary,
)
from aef_domain.contexts.workflows.domain.queries import (
    GetWorkflowDetailQuery,
    ListWorkflowsQuery,
)
from aef_domain.contexts.workflows.slices.get_workflow_detail import (
    GetWorkflowDetailHandler,
)
from aef_domain.contexts.workflows.slices.list_workflows import ListWorkflowsHandler

if TYPE_CHECKING:
    from aef_domain.contexts.workflows.domain.read_models import (
        WorkflowDetail,
    )
    from aef_domain.contexts.workflows.domain.read_models import (
        WorkflowSummary as DomainWorkflowSummary,
    )

router = APIRouter(prefix="/workflows", tags=["workflows"])


def _domain_summary_to_api(summary: DomainWorkflowSummary) -> WorkflowSummary:
    """Convert domain WorkflowSummary to API WorkflowSummary."""
    return WorkflowSummary(
        id=summary.id,
        name=summary.name,
        workflow_type=summary.workflow_type,
        status=summary.status,
        phase_count=summary.phase_count,
        created_at=summary.created_at,
    )


def _domain_detail_to_api(detail: WorkflowDetail) -> WorkflowResponse:
    """Convert domain WorkflowDetail to API WorkflowResponse."""
    from decimal import Decimal

    phases = []
    for i, p in enumerate(detail.phases, 1):
        if isinstance(p, dict):
            phase_info = PhaseInfo(
                phase_id=p.get("id", p.get("phase_id", f"phase-{i}")),
                name=p.get("name", f"Phase {i}"),
                order=i,
                description=p.get("description"),
                status=p.get("status", "pending"),
                artifact_id=p.get("artifact_id"),
                input_tokens=p.get("input_tokens", 0),
                output_tokens=p.get("output_tokens", 0),
                total_tokens=p.get("total_tokens", 0),
                duration_seconds=p.get("duration_seconds", 0.0),
                cost_usd=Decimal(str(p.get("cost_usd", "0"))),
                session_id=p.get("session_id"),
            )
        else:
            phase_info = PhaseInfo(
                phase_id=p.id,
                name=p.name,
                order=i,
                description=None,
                status=p.status,
                artifact_id=None,
                input_tokens=p.input_tokens,
                output_tokens=p.output_tokens,
                total_tokens=p.total_tokens,
                duration_seconds=p.duration_seconds,
                cost_usd=Decimal(str(p.cost_usd)),
                session_id=p.session_id,
            )
        phases.append(phase_info)

    return WorkflowResponse(
        id=detail.id,
        name=detail.name,
        description=detail.description,
        workflow_type=detail.workflow_type,
        classification=detail.classification,
        status=detail.status,
        phases=phases,
        created_at=detail.created_at,
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
    # Get projection manager and create handler
    manager = get_projection_manager()
    handler = ListWorkflowsHandler(manager.workflow_list)

    # Build and execute query
    offset = (page - 1) * page_size
    query = ListWorkflowsQuery(
        status_filter=status,
        limit=page_size,
        offset=offset,
    )
    summaries = await handler.handle(query)

    # Get total count (without pagination) for proper pagination info
    total_query = ListWorkflowsQuery(status_filter=status, limit=10000, offset=0)
    all_summaries = await handler.handle(total_query)
    total = len(all_summaries)

    return WorkflowListResponse(
        workflows=[_domain_summary_to_api(s) for s in summaries],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{workflow_id}", response_model=WorkflowResponse)
async def get_workflow(workflow_id: str) -> WorkflowResponse:
    """Get workflow details by ID."""
    # Get projection manager and create handler
    manager = get_projection_manager()
    handler = GetWorkflowDetailHandler(manager.workflow_detail)

    # Execute query
    query = GetWorkflowDetailQuery(workflow_id=workflow_id)
    detail = await handler.handle(query)

    if detail is None:
        raise HTTPException(status_code=404, detail=f"Workflow {workflow_id} not found")

    return _domain_detail_to_api(detail)


@router.get("/{workflow_id}/history", response_model=ExecutionHistoryResponse)
async def get_workflow_history(workflow_id: str) -> ExecutionHistoryResponse:
    """Get execution history for a workflow."""
    # Get projection manager and create handler
    manager = get_projection_manager()
    handler = GetWorkflowDetailHandler(manager.workflow_detail)

    # Execute query
    query = GetWorkflowDetailQuery(workflow_id=workflow_id)
    detail = await handler.handle(query)

    if detail is None:
        raise HTTPException(status_code=404, detail=f"Workflow {workflow_id} not found")

    # For now, return empty history (sessions/artifacts not yet implemented in history)
    return ExecutionHistoryResponse(
        workflow_id=workflow_id,
        workflow_name=detail.name,
        executions=[],
        total_executions=0,
    )
