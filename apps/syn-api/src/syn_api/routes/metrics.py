"""Metrics API endpoints and service operations.

Provides aggregated dashboard metrics with optional per-phase breakdown.
"""

from __future__ import annotations

import logging
from decimal import Decimal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from syn_api._wiring import (
    ensure_connected,
    get_canonical_usage_query,
    get_projection_mgr,
)
from syn_api.types import (
    DashboardMetrics,
    Err,
    MetricsError,
    Ok,
    Result,
)

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
    duration_seconds: float | None = None
    """Accumulated seconds across every execution of this phase.

    ``None`` while no execution of the phase has reported a duration. This
    projection aggregates across executions, so unlike the per-execution
    surfaces there is no single ``started_at`` to compute a live figure from --
    but ``0.0`` would still read as "this phase takes no time", which is the
    same false measurement.
    """
    artifact_count: int = 0


class MetricsResponse(BaseModel):
    """Aggregated metrics response."""

    total_workflows: int = 0
    completed_workflows: int = 0
    failed_workflows: int = 0
    total_sessions: int = 0
    total_input_tokens: int
    total_output_tokens: int
    total_cache_creation_tokens: int
    total_cache_read_tokens: int
    total_tokens: int
    total_cost_usd: Decimal = Decimal("0")
    total_artifacts: int = 0
    total_artifact_bytes: int = 0
    phases: list[PhaseMetrics] = Field(default_factory=list)


# =============================================================================
# Service functions (importable by tests)
# =============================================================================


async def get_dashboard_metrics(
    workflow_id: str | None = None,  # noqa: ARG001
) -> Result[DashboardMetrics, MetricsError]:
    """Get aggregated dashboard metrics.

    Args:
        workflow_id: Optional filter by workflow ID.

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
                total_cache_creation_tokens=data.total_cache_creation_tokens,
                total_cache_read_tokens=data.total_cache_read_tokens,
                total_tokens=data.total_tokens,
                # Lane 2: cost is enriched at the endpoint from execution_cost (#695)
                total_cost_usd=Decimal("0"),
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
                # Lane 2: phase cost is enriched at the endpoint from execution_cost (#695)
                cost_usd=Decimal("0"),
                duration_seconds=d.get("duration_seconds"),
                artifact_count=d.get("artifact_count", 0),
            )
            for pid, d in phases_data.items()
        ]
    except Exception:
        logger.debug("Could not build phase metrics for workflow %s", workflow_id, exc_info=True)
        return []


class MetricsUnavailableError(Exception):
    """The usage totals could not be read, so none may be reported.

    Deliberately NOT a zero-valued result. Returning empty totals made a
    Timescale outage indistinguishable from a system that had done no work -
    0 tokens, $0.00 and 0 sessions rendered beside populated workflow and
    artifact counts, which reads as fact. A silently-cheap number is the
    dangerous kind; that is the premise of this entire change, and it applies
    to the error path too.
    """


async def _canonical_totals(workflow_id: str | None):
    """Canonical token/cost totals, narrowed to one workflow when asked.

    Raises:
        MetricsUnavailableError: the totals could not be read.
    """
    try:
        query_svc = get_canonical_usage_query()
        if workflow_id is None:
            return await query_svc.totals()
        manager = get_projection_mgr()
        summaries = await manager.workflow_execution_list.get_by_workflow_id(workflow_id)
        return await query_svc.totals(execution_ids={s.workflow_execution_id for s in summaries})
    except Exception as exc:
        logger.warning("Failed to read canonical usage totals", exc_info=True)
        raise MetricsUnavailableError(
            "usage totals are unavailable: the observability store could not be read"
        ) from exc


@router.get("", response_model=MetricsResponse)
async def get_metrics_endpoint(
    workflow_id: str | None = Query(None, description="Filter by workflow ID"),
) -> MetricsResponse:
    """Get aggregated metrics across all workflows or for a specific workflow."""
    result = await get_dashboard_metrics(workflow_id=workflow_id)

    if isinstance(result, Err):
        # Same reasoning as MetricsUnavailableError: an all-zero body is a
        # claim about the system, and this code path cannot support it.
        raise HTTPException(
            status_code=503, detail="metrics are unavailable: the read model could not be queried"
        )

    m = result.value
    phases = await _build_phase_metrics(workflow_id) if workflow_id else []

    # Tokens, cost and session count come from the ONE canonical definition, the same
    # one the activity heatmap reads (#932). They previously came from Lane 1
    # SessionCompleted events while the heatmap read Lane 2 observations, so
    # the two cards quoted 9,151,116 tokens beside 10,002,629 for the same
    # reality. Workflow/artifact counts stay on the projection: those are
    # domain lifecycle facts, not observed telemetry.
    try:
        totals = await _canonical_totals(workflow_id)
    except MetricsUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return MetricsResponse(
        total_workflows=m.total_workflows,
        completed_workflows=m.completed_workflows,
        failed_workflows=m.failed_workflows,
        # Sessions come from the canonical source too. Counting them in the
        # projection instead meant the card saw every FAILED session but no
        # DELEGATE session, while the heatmap saw every delegate and no
        # failure - two honest counts of two different populations.
        total_sessions=totals.sessions,
        total_input_tokens=totals.input_tokens,
        total_output_tokens=totals.output_tokens,
        total_cache_creation_tokens=totals.cache_creation_tokens,
        total_cache_read_tokens=totals.cache_read_tokens,
        total_tokens=totals.total_tokens,
        total_cost_usd=totals.cost_usd,
        total_artifacts=m.total_artifacts,
        total_artifact_bytes=m.total_artifact_bytes,
        phases=phases,
    )
