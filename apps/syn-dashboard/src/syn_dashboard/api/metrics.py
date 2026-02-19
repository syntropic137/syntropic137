"""Metrics API endpoints — thin wrapper over syn_api."""

from __future__ import annotations

import logging
from decimal import Decimal

from fastapi import APIRouter, Query

import syn_api.v1.metrics as met
from syn_api._wiring import ensure_connected, get_projection_mgr
from syn_api.types import Err
from syn_dashboard.models.schemas import MetricsResponse, PhaseMetrics

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/metrics", tags=["metrics"])


async def _build_phase_metrics(workflow_id: str) -> list[PhaseMetrics]:
    """Return pre-aggregated per-phase metrics from the projection store (O(1) read)."""
    await ensure_connected()
    try:
        manager = get_projection_mgr()
        phases_data = await manager.workflow_phase_metrics.get_phase_metrics(workflow_id)
        return [
            PhaseMetrics(
                phase_id=pid,
                phase_name=d.get("phase_name", pid),
                status=d.get("status", "completed"),
                input_tokens=d.get("input_tokens", 0),
                output_tokens=d.get("output_tokens", 0),
                total_tokens=d.get("total_tokens", 0),
                cost_usd=Decimal(str(d.get("cost_usd", "0"))),
                duration_seconds=d.get("duration_seconds", 0.0),
                artifact_count=d.get("artifact_count", 0),
            )
            for pid, d in phases_data.items()
        ]
    except Exception:
        logger.debug("Could not build phase metrics for workflow %s", workflow_id, exc_info=True)
        return []


@router.get("", response_model=MetricsResponse)
async def get_metrics(
    workflow_id: str | None = Query(None, description="Filter by workflow ID"),
) -> MetricsResponse:
    """Get aggregated metrics across all workflows or for a specific workflow."""
    result = await met.get_dashboard_metrics(workflow_id=workflow_id)

    if isinstance(result, Err):
        return MetricsResponse()

    m = result.value
    phases = await _build_phase_metrics(workflow_id) if workflow_id else []

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
        phases=phases,
    )
