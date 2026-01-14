"""Metrics API endpoints."""

from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Query

from aef_adapters.projections import get_projection_manager
from aef_dashboard.models.schemas import MetricsResponse
from aef_domain.contexts.metrics.domain.queries import GetDashboardMetricsQuery
from aef_domain.contexts.metrics.slices.get_metrics import GetDashboardMetricsHandler

router = APIRouter(prefix="/metrics", tags=["metrics"])


@router.get("", response_model=MetricsResponse)
async def get_metrics(
    workflow_id: str | None = Query(None, description="Filter by workflow ID"),
) -> MetricsResponse:
    """Get aggregated metrics across all workflows or for a specific workflow.

    When workflow_id is provided, metrics are computed from sessions belonging
    to that workflow. When omitted, returns global metrics from all workflows.
    """
    manager = get_projection_manager()

    if workflow_id:
        # Per-workflow metrics: aggregate from sessions for this workflow
        sessions = await manager.session_list.get_by_workflow(workflow_id)
        artifacts = await manager.artifact_list.get_by_workflow(workflow_id)

        # Aggregate session metrics
        total_sessions = len(sessions)
        total_input_tokens = sum(s.input_tokens for s in sessions)
        total_output_tokens = sum(s.output_tokens for s in sessions)
        total_tokens = total_input_tokens + total_output_tokens
        total_cost_usd = sum(Decimal(str(s.total_cost_usd)) for s in sessions)
        total_artifacts = len(artifacts)
        total_artifact_bytes = sum(a.size_bytes or 0 for a in artifacts)

        return MetricsResponse(
            total_workflows=1,  # Single workflow
            completed_workflows=0,  # Not tracked per-workflow
            failed_workflows=0,
            total_sessions=total_sessions,
            total_input_tokens=total_input_tokens,
            total_output_tokens=total_output_tokens,
            total_tokens=total_tokens,
            total_cost_usd=Decimal(str(total_cost_usd)),
            total_artifacts=total_artifacts,
            total_artifact_bytes=total_artifact_bytes,
            phases=[],  # TODO: Phase-level metrics per workflow
        )

    # Global metrics (dashboard view)
    handler = GetDashboardMetricsHandler(manager.dashboard_metrics)
    query = GetDashboardMetricsQuery()
    metrics = await handler.handle(query)

    return MetricsResponse(
        total_workflows=metrics.total_workflows,
        completed_workflows=metrics.completed_workflows,
        failed_workflows=metrics.failed_workflows,
        total_sessions=metrics.total_sessions,
        total_input_tokens=metrics.total_input_tokens,
        total_output_tokens=metrics.total_output_tokens,
        total_tokens=metrics.total_tokens,
        total_cost_usd=metrics.total_cost_usd,
        total_artifacts=metrics.total_artifacts,
        total_artifact_bytes=0,  # Not tracked globally yet
        phases=[],  # Phase-level metrics not implemented yet
    )
