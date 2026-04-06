"""Metrics API endpoints and service operations.

Provides aggregated dashboard metrics with optional per-phase breakdown.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import TYPE_CHECKING

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from syn_api._wiring import ensure_connected, get_projection_mgr
from syn_api.types import (
    DashboardMetrics,
    Err,
    MetricsError,
    Ok,
    Result,
)

if TYPE_CHECKING:
    from syn_api.auth import AuthContext

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/metrics", tags=["metrics"])


# =============================================================================
# Response Models
# =============================================================================


class PhaseMetrics(BaseModel):
    """Metrics for a single phase."""

    phase_id: str
    phase_name: str
    status: str
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cost_usd: Decimal = Decimal("0")
    duration_seconds: float = 0.0
    artifact_count: int = 0


class MetricsResponse(BaseModel):
    """Aggregated metrics response."""

    total_workflows: int = 0
    completed_workflows: int = 0
    failed_workflows: int = 0
    total_sessions: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_tokens: int = 0
    total_cost_usd: Decimal = Decimal("0")
    total_artifacts: int = 0
    total_artifact_bytes: int = 0
    phases: list[PhaseMetrics] = Field(default_factory=list)


# =============================================================================
# Service functions (importable by tests)
# =============================================================================


async def get_dashboard_metrics(
    workflow_id: str | None = None,  # noqa: ARG001
    auth: AuthContext | None = None,  # noqa: ARG001
) -> Result[DashboardMetrics, MetricsError]:
    """Get aggregated dashboard metrics.

    Args:
        workflow_id: Optional filter by workflow ID.
        auth: Optional authentication context.

    Returns:
        Ok(DashboardMetrics) on success, Err(MetricsError) on failure.
    """
    await ensure_connected()
    try:
        manager = get_projection_mgr()
        projection = manager.dashboard_metrics
        data = await projection.get_metrics()

        return Ok(
            DashboardMetrics(
                total_workflows=data.total_workflows,
                completed_workflows=data.completed_workflows,
                failed_workflows=data.failed_workflows,
                total_sessions=data.total_sessions,
                total_input_tokens=data.total_input_tokens,
                total_output_tokens=data.total_output_tokens,
                total_tokens=data.total_tokens,
                total_cost_usd=Decimal(str(data.total_cost_usd)),
                total_artifacts=data.total_artifacts,
                total_artifact_bytes=data.total_artifact_bytes,
            )
        )
    except Exception as e:
        return Err(MetricsError.QUERY_FAILED, message=str(e))


# =============================================================================
# HTTP Endpoints
# =============================================================================


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
async def get_metrics_endpoint(
    workflow_id: str | None = Query(None, description="Filter by workflow ID"),
) -> MetricsResponse:
    """Get aggregated metrics across all workflows or for a specific workflow."""
    result = await get_dashboard_metrics(workflow_id=workflow_id)

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
