"""Metrics API endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Query

from aef_adapters.projections import get_projection_manager
from aef_dashboard.models.schemas import MetricsResponse
from aef_domain.contexts.metrics.domain.queries import GetDashboardMetricsQuery
from aef_domain.contexts.metrics.slices.get_metrics import GetDashboardMetricsHandler

router = APIRouter(prefix="/metrics", tags=["metrics"])


@router.get("", response_model=MetricsResponse)
async def get_metrics(
    workflow_id: str | None = Query(  # noqa: ARG001 - API parameter for future use
        None, description="Filter by workflow ID"
    ),
) -> MetricsResponse:
    """Get aggregated metrics across all workflows or for a specific workflow."""
    # Get projection manager and create handler
    manager = get_projection_manager()
    handler = GetDashboardMetricsHandler(manager.dashboard_metrics)

    # Execute query
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
        total_artifact_bytes=0,  # Not tracked yet
        phases=[],  # Phase-level metrics not implemented yet
    )
