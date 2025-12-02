"""Workflow API endpoints."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException, Query

from aef_adapters.storage import (
    get_artifact_repository,
    get_session_repository,
    get_workflow_repository,
)
from aef_dashboard.models.schemas import (
    ExecutionHistoryResponse,
    ExecutionRun,
    PhaseInfo,
    PhaseMetrics,
    WorkflowListResponse,
    WorkflowResponse,
    WorkflowSummary,
)

if TYPE_CHECKING:
    from aef_domain.contexts.workflows._shared.WorkflowAggregate import WorkflowAggregate

router = APIRouter(prefix="/workflows", tags=["workflows"])


def _workflow_to_summary(workflow: WorkflowAggregate) -> WorkflowSummary:
    """Convert a WorkflowAggregate to a WorkflowSummary."""
    return WorkflowSummary(
        id=str(workflow.id) if workflow.id else "",
        name=workflow.name or "Unnamed",
        workflow_type=workflow._workflow_type or "unknown",
        status=workflow.status.value if workflow.status else "pending",
        phase_count=len(workflow.phases) if workflow.phases else 0,
        created_at=None,  # Not tracked in current aggregate
    )


def _workflow_to_response(workflow: WorkflowAggregate) -> WorkflowResponse:
    """Convert a WorkflowAggregate to a WorkflowResponse."""
    phases = [
        PhaseInfo(
            phase_id=p.phase_id,
            name=p.name,
            order=p.order,
            description=p.description,
        )
        for p in (workflow.phases or [])
    ]

    return WorkflowResponse(
        id=str(workflow.id) if workflow.id else "",
        name=workflow.name or "Unnamed",
        description=workflow._description,
        workflow_type=workflow._workflow_type or "unknown",
        classification=workflow._classification or "standard",
        status=workflow.status.value if workflow.status else "pending",
        phases=phases,
        created_at=None,  # Not tracked in current aggregate
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
    repo = get_workflow_repository()

    # Get all workflows from the repository
    # Note: In production, this would use proper pagination
    all_workflows = repo.get_all()

    # Filter by status if provided
    if status:
        all_workflows = [w for w in all_workflows if w.status and w.status.value == status]

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
    repo = get_workflow_repository()
    workflow = await repo.get_by_id(workflow_id)

    if workflow is None:
        raise HTTPException(status_code=404, detail=f"Workflow {workflow_id} not found")

    return _workflow_to_response(workflow)


@router.get("/{workflow_id}/history", response_model=ExecutionHistoryResponse)
async def get_workflow_history(workflow_id: str) -> ExecutionHistoryResponse:
    """Get execution history for a workflow."""
    workflow_repo = get_workflow_repository()
    session_repo = get_session_repository()
    artifact_repo = get_artifact_repository()

    workflow = await workflow_repo.get_by_id(workflow_id)
    if workflow is None:
        raise HTTPException(status_code=404, detail=f"Workflow {workflow_id} not found")

    # Get all sessions for this workflow
    sessions = session_repo.get_by_workflow(workflow_id)

    # Group sessions by execution (phase_id pattern)
    # In a real implementation, we'd have execution_id on sessions
    executions: list[ExecutionRun] = []

    if sessions:
        # For now, create a single execution with all sessions
        total_tokens = sum(s.tokens.total_tokens for s in sessions)
        total_cost = sum(s.cost.total_cost_usd for s in sessions)

        # Get phase metrics
        phase_metrics: list[PhaseMetrics] = []
        for phase in workflow.phases or []:
            phase_sessions = [s for s in sessions if s.phase_id == phase.phase_id]
            artifacts = artifact_repo.get_by_phase(workflow_id, phase.phase_id)

            if phase_sessions:
                phase_tokens = sum(s.tokens.total_tokens for s in phase_sessions)
                phase_cost = sum(s.cost.total_cost_usd for s in phase_sessions)
                phase_duration = sum(s.duration_seconds or 0 for s in phase_sessions)
                phase_status = (
                    "completed"
                    if all(s.status.value == "completed" for s in phase_sessions)
                    else "failed"
                )
            else:
                phase_tokens = 0
                phase_cost = 0
                phase_duration = 0.0
                phase_status = "pending"

            phase_metrics.append(
                PhaseMetrics(
                    phase_id=phase.phase_id,
                    phase_name=phase.name,
                    status=phase_status,
                    total_tokens=phase_tokens,
                    cost_usd=phase_cost,
                    duration_seconds=phase_duration,
                    artifact_count=len(artifacts),
                )
            )

        # Determine overall status
        if all(pm.status == "completed" for pm in phase_metrics):
            exec_status = "completed"
        elif any(pm.status == "failed" for pm in phase_metrics):
            exec_status = "failed"
        else:
            exec_status = "running"

        executions.append(
            ExecutionRun(
                execution_id=f"exec-{workflow_id}",
                status=exec_status,
                started_at=min((s._started_at for s in sessions if s._started_at), default=None),
                completed_at=max(
                    (s._completed_at for s in sessions if s._completed_at), default=None
                ),
                total_tokens=total_tokens,
                total_cost_usd=total_cost,
                phase_results=phase_metrics,
            )
        )

    return ExecutionHistoryResponse(
        workflow_id=workflow_id,
        workflow_name=workflow.name or "Unnamed",
        executions=executions,
        total_executions=len(executions),
    )
