"""Metrics API endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Query

from aef_dashboard.models.schemas import MetricsResponse
from aef_dashboard.read_models import get_metrics as get_metrics_from_db

router = APIRouter(prefix="/metrics", tags=["metrics"])


@router.get("", response_model=MetricsResponse)
async def get_metrics(
    workflow_id: str | None = Query(  # noqa: ARG001 - API parameter for future use
        None, description="Filter by workflow ID"
    ),
) -> MetricsResponse:
    """Get aggregated metrics across all workflows or for a specific workflow."""
    # Get metrics from the read model (direct PostgreSQL queries)
    metrics = await get_metrics_from_db()

    return MetricsResponse(
        total_workflows=metrics["total_workflows"],
        completed_workflows=metrics["completed_workflows"],
        failed_workflows=metrics["failed_workflows"],
        total_sessions=metrics["total_sessions"],
        total_input_tokens=0,  # Not tracked yet
        total_output_tokens=0,  # Not tracked yet
        total_tokens=metrics["total_tokens"],
        total_cost_usd=metrics["total_cost_usd"],
        total_artifacts=metrics["total_artifacts"],
        total_artifact_bytes=metrics["total_artifact_bytes"],
        phases=[],  # Phase-level metrics not implemented yet
    )
