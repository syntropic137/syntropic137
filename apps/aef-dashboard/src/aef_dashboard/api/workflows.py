"""Workflow TEMPLATE API endpoints.

These endpoints manage workflow TEMPLATES (definitions).
For execution details, see /api/executions.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException, Query

from aef_adapters.projections import get_projection_manager
from aef_dashboard.models.schemas import (
    ExecutionHistoryResponse,
    ExecutionRunListResponse,
    ExecutionRunSummary,
    PhaseDefinition,
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
    """Convert domain WorkflowSummary to API WorkflowSummary.

    Templates don't have status - only runs_count.
    """
    return WorkflowSummary(
        id=summary.id,
        name=summary.name,
        workflow_type=summary.workflow_type,
        phase_count=summary.phase_count,
        created_at=summary.created_at,
        runs_count=summary.runs_count,
    )


def _domain_detail_to_api(detail: WorkflowDetail) -> WorkflowResponse:
    """Convert domain WorkflowDetail to API WorkflowResponse.

    Templates don't have execution status - only definition info.
    """
    phases = []
    for i, p in enumerate(detail.phases, 1):
        if isinstance(p, dict):
            phase_def = PhaseDefinition(
                phase_id=str(p.get("id") or p.get("phase_id") or f"phase-{i}"),
                name=str(p.get("name") or f"Phase {i}"),
                order=p.get("order", i),
                description=p.get("description"),
                agent_type=p.get("agent_type", ""),
                prompt_template=p.get("prompt_template"),
                timeout_seconds=p.get("timeout_seconds", 300),
                allowed_tools=p.get("allowed_tools", []),
            )
        else:
            phase_def = PhaseDefinition(
                phase_id=p.id,
                name=p.name,
                order=getattr(p, "order", i),
                description=getattr(p, "description", None),
                agent_type=getattr(p, "agent_type", ""),
                prompt_template=getattr(p, "prompt_template", None),
                timeout_seconds=getattr(p, "timeout_seconds", 300),
                allowed_tools=list(getattr(p, "allowed_tools", [])),
            )
        phases.append(phase_def)

    return WorkflowResponse(
        id=detail.id,
        name=detail.name,
        description=detail.description,
        workflow_type=detail.workflow_type,
        classification=detail.classification,
        phases=phases,
        created_at=detail.created_at,
        runs_count=detail.runs_count,
        runs_link=f"/api/workflows/{detail.id}/runs",
    )


@router.get("", response_model=WorkflowListResponse)
async def list_workflows(
    workflow_type: str | None = Query(None, description="Filter by workflow type"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
) -> WorkflowListResponse:
    """List all workflow templates.

    Note: Templates don't have status. Use /api/executions for execution status.
    """
    manager = get_projection_manager()
    handler = ListWorkflowsHandler(manager.workflow_list)

    offset = (page - 1) * page_size
    query = ListWorkflowsQuery(
        workflow_type_filter=workflow_type,
        limit=page_size,
        offset=offset,
    )
    summaries = await handler.handle(query)

    # Get total count
    total_query = ListWorkflowsQuery(workflow_type_filter=workflow_type, limit=10000, offset=0)
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


@router.get("/{workflow_id}/runs", response_model=ExecutionRunListResponse)
async def list_workflow_runs(workflow_id: str) -> ExecutionRunListResponse:
    """List all execution runs for a workflow.

    Returns a list of execution summaries for the specified workflow,
    sorted by most recent first.
    """
    from decimal import Decimal

    manager = get_projection_manager()

    # Get workflow name for response
    handler = GetWorkflowDetailHandler(manager.workflow_detail)
    query = GetWorkflowDetailQuery(workflow_id=workflow_id)
    detail = await handler.handle(query)

    if detail is None:
        raise HTTPException(status_code=404, detail=f"Workflow {workflow_id} not found")

    # Get executions from projection
    executions = await manager.execution_list.get_by_workflow_id(workflow_id)

    # Convert to API response
    runs = [
        ExecutionRunSummary(
            execution_id=e.execution_id,
            workflow_id=e.workflow_id,
            workflow_name=e.workflow_name or detail.name,
            status=e.status,
            started_at=e.started_at,
            completed_at=e.completed_at,
            completed_phases=e.completed_phases,
            total_phases=e.total_phases,
            total_tokens=e.total_tokens,
            total_cost_usd=Decimal(str(e.total_cost_usd)),
            error_message=e.error_message,
        )
        for e in executions
    ]

    return ExecutionRunListResponse(
        runs=runs,
        total=len(runs),
        workflow_id=workflow_id,
        workflow_name=detail.name,
    )


@router.get("/{workflow_id}/history", response_model=ExecutionHistoryResponse)
async def get_workflow_history(workflow_id: str) -> ExecutionHistoryResponse:
    """Get execution history for a workflow.

    DEPRECATED: Use /workflows/{workflow_id}/runs instead.
    """
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
