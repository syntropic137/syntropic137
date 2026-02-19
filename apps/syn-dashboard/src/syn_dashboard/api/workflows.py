"""Workflow TEMPLATE API endpoints — thin wrapper over syn_api.

These endpoints manage workflow TEMPLATES (definitions).
For execution details, see /api/executions.
"""

from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, HTTPException, Query

import syn_api.v1.executions as ex
import syn_api.v1.workflows as wf
from syn_api.types import Err
from syn_dashboard.models.schemas import (
    ExecutionHistoryResponse,
    ExecutionRunListResponse,
    ExecutionRunSummary,
    PhaseDefinition,
    WorkflowListResponse,
    WorkflowResponse,
    WorkflowSummary,
)

router = APIRouter(prefix="/workflows", tags=["workflows"])


@router.get("", response_model=WorkflowListResponse)
async def list_workflows(
    workflow_type: str | None = Query(None, description="Filter by workflow type"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    order_by: str | None = Query(None, description="Sort field (prefix with - for descending)"),
) -> WorkflowListResponse:
    """List all workflow templates."""
    offset = (page - 1) * page_size

    # Fetch all matching workflows, sort, then paginate
    all_result = await wf.list_workflows(
        workflow_type=workflow_type,
        limit=10000,
        offset=0,
    )

    if isinstance(all_result, Err):
        raise HTTPException(status_code=500, detail=all_result.message)

    summaries = [
        WorkflowSummary(
            id=s.id,
            name=s.name,
            workflow_type=s.workflow_type,
            phase_count=s.phase_count,
            created_at=s.created_at,
            runs_count=s.runs_count,
        )
        for s in all_result.value
    ]

    # Apply sort order before pagination
    if order_by:
        desc = order_by.startswith("-")
        field = order_by.lstrip("-")
        if field in {"runs_count", "name", "workflow_type", "phase_count", "created_at"}:
            summaries.sort(key=lambda s: getattr(s, field, 0) or 0, reverse=desc)

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
        created_at=detail.created_at,
        runs_count=detail.runs_count,
        runs_link=f"/api/workflows/{detail.id}/runs",
    )


@router.get("/{workflow_id}/runs", response_model=ExecutionRunListResponse)
async def list_workflow_runs(workflow_id: str) -> ExecutionRunListResponse:
    """List all execution runs for a workflow."""
    # Get workflow name
    wf_result = await wf.get_workflow(workflow_id)
    if isinstance(wf_result, Err):
        raise HTTPException(status_code=404, detail=f"Workflow {workflow_id} not found")

    workflow_name = wf_result.value.name

    # Get executions
    exec_result = await ex.list_(workflow_id=workflow_id)
    if isinstance(exec_result, Err):
        raise HTTPException(status_code=500, detail=exec_result.message)

    runs = [
        ExecutionRunSummary(
            workflow_execution_id=e.workflow_execution_id,
            workflow_id=e.workflow_id,
            workflow_name=e.workflow_name or workflow_name,
            status=e.status,
            started_at=e.started_at,
            completed_at=e.completed_at,
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
