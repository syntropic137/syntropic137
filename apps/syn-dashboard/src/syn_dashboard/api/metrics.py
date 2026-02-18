"""Metrics API endpoints — thin wrapper over syn_api."""

from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Query

import syn_api.v1.metrics as met
from syn_api.types import Err
from syn_dashboard.models.schemas import MetricsResponse

router = APIRouter(prefix="/metrics", tags=["metrics"])


@router.get("", response_model=MetricsResponse)
async def get_metrics(
    workflow_id: str | None = Query(None, description="Filter by workflow ID"),
) -> MetricsResponse:
    """Get aggregated metrics across all workflows or for a specific workflow."""
    result = await met.get_dashboard_metrics(workflow_id=workflow_id)

    if isinstance(result, Err):
        return MetricsResponse()

    m = result.value
    return MetricsResponse(
        total_workflows=m.total_workflows,
        completed_workflows=m.completed_workflows,
        failed_workflows=m.failed_workflows,
        total_sessions=m.total_sessions,
        total_input_tokens=m.total_input_tokens,
        total_output_tokens=m.total_output_tokens,
        total_tokens=m.total_tokens,
        total_cost_usd=Decimal(str(m.total_cost_usd)),
        total_artifacts=m.total_artifacts,
        total_artifact_bytes=m.total_artifact_bytes,
        phases=[],
    )
