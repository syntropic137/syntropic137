"""Metrics API endpoints."""

from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Query

from aef_adapters.storage import (
    get_artifact_repository,
    get_session_repository,
    get_workflow_repository,
)
from aef_dashboard.models.schemas import MetricsResponse, PhaseMetrics

router = APIRouter(prefix="/metrics", tags=["metrics"])


@router.get("", response_model=MetricsResponse)
async def get_metrics(
    workflow_id: str | None = Query(None, description="Filter by workflow ID"),
) -> MetricsResponse:
    """Get aggregated metrics across all workflows or for a specific workflow."""
    workflow_repo = get_workflow_repository()
    session_repo = get_session_repository()
    artifact_repo = get_artifact_repository()

    # Get workflows
    if workflow_id:
        workflow = await workflow_repo.get_by_id(workflow_id)
        workflows = [workflow] if workflow else []
    else:
        workflows = workflow_repo.get_all()

    # Get sessions
    sessions = session_repo.get_by_workflow(workflow_id) if workflow_id else session_repo.get_all()

    # Get artifacts
    if workflow_id:
        artifacts = artifact_repo.get_by_workflow(workflow_id)
    else:
        artifacts = artifact_repo.get_all()

    # Calculate workflow metrics
    total_workflows = len(workflows)
    completed_workflows = sum(1 for w in workflows if w.status and w.status.value == "completed")
    failed_workflows = sum(1 for w in workflows if w.status and w.status.value == "failed")

    # Calculate session/token metrics
    total_sessions = len(sessions)
    total_input_tokens = sum(s.tokens.input_tokens for s in sessions)
    total_output_tokens = sum(s.tokens.output_tokens for s in sessions)
    total_tokens = sum(s.tokens.total_tokens for s in sessions)
    total_cost = sum(s.cost.total_cost_usd for s in sessions)

    # Calculate artifact metrics
    total_artifacts = len(artifacts)
    total_artifact_bytes = sum(a._size_bytes for a in artifacts)

    # Calculate phase-level metrics if single workflow
    phase_metrics: list[PhaseMetrics] = []
    if workflow_id and workflows:
        workflow = workflows[0]
        for phase in workflow.phases or []:
            phase_sessions = [s for s in sessions if s.phase_id == phase.phase_id]
            phase_artifacts = artifact_repo.get_by_phase(workflow_id, phase.phase_id)

            if phase_sessions:
                phase_input_tokens = sum(s.tokens.input_tokens for s in phase_sessions)
                phase_output_tokens = sum(s.tokens.output_tokens for s in phase_sessions)
                phase_total_tokens = sum(s.tokens.total_tokens for s in phase_sessions)
                phase_cost = sum(s.cost.total_cost_usd for s in phase_sessions)
                phase_duration = sum(s.duration_seconds or 0 for s in phase_sessions)

                # Determine phase status
                if all(s.status.value == "completed" for s in phase_sessions):
                    status = "completed"
                elif any(s.status.value == "failed" for s in phase_sessions):
                    status = "failed"
                elif any(s.status.value == "running" for s in phase_sessions):
                    status = "running"
                else:
                    status = "pending"
            else:
                phase_input_tokens = 0
                phase_output_tokens = 0
                phase_total_tokens = 0
                phase_cost = Decimal("0")
                phase_duration = 0.0
                status = "pending"

            phase_metrics.append(
                PhaseMetrics(
                    phase_id=phase.phase_id,
                    phase_name=phase.name,
                    status=status,
                    input_tokens=phase_input_tokens,
                    output_tokens=phase_output_tokens,
                    total_tokens=phase_total_tokens,
                    cost_usd=phase_cost,
                    duration_seconds=phase_duration,
                    artifact_count=len(phase_artifacts),
                )
            )

    return MetricsResponse(
        total_workflows=total_workflows,
        completed_workflows=completed_workflows,
        failed_workflows=failed_workflows,
        total_sessions=total_sessions,
        total_input_tokens=total_input_tokens,
        total_output_tokens=total_output_tokens,
        total_tokens=total_tokens,
        total_cost_usd=total_cost,
        total_artifacts=total_artifacts,
        total_artifact_bytes=total_artifact_bytes,
        phases=phase_metrics,
    )
