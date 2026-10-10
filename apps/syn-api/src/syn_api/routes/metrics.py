"""Metrics API endpoints and service operations.

Provides aggregated dashboard metrics with optional per-phase breakdown.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from syn_api._wiring import (
    ensure_connected,
    get_canonical_usage_query,
    get_execution_cost_query,
    get_phase_profile_query,
    get_projection_mgr,
)
from syn_api.services.shipped_ledger import shipped_metrics_service
from syn_api.types import (
    DashboardMetrics,
    Err,
    MetricsError,
    Ok,
    PhaseProfilesResponse,
    Result,
    ShippedMetricsResponse,
)
from syn_domain.contexts.orchestration import SHIPPED_WINDOW_DAYS, ShippedMetricsQueryService
from syn_domain.pagination import Page
from syn_shared.pricing import canonical_cost_usd

if TYPE_CHECKING:
    from syn_domain.contexts.agent_sessions import CanonicalTotals

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
    """What this phase cost, summed over every execution of the workflow.

    Read from the same per-phase source the execution detail page uses
    (``ExecutionCostQueryService``, Lane 2), so a workflow's per-phase cost
    reconciles with the phases of its executions.
    """
    unpriced_observation_count: int = 0
    """Observations in this phase that carried no usable rate (#890 contract).

    Non-zero means ``cost_usd`` is incomplete: a lower bound, not the total. A
    phase with ``cost_usd == 0`` and a non-zero count is UNKNOWN, not free.
    """
    cost_in_progress: bool = False
    """True while any execution still has this phase open.

    A running phase's cost is only attributed once its session summary lands;
    until then ``cost_by_phase`` has no entry for it, so ``cost_usd`` omits the
    run in flight. True means ``cost_usd`` is a lower bound "so far", never a
    settled figure (the workflow-level form of #1048).
    """
    duration_seconds: float | None = None
    """Seconds this phase has run in total, or ``None`` when nothing knows.

    Nullable for the same reason every other duration on this API is: 0.0 is a
    measurement, and a phase that just started, never started, or ended without
    anyone recording an elapsed time has not been measured. This field reported
    0.0 for a phase it simultaneously reported as ``running``.
    """
    artifact_count: int = 0


class ExecutionStatusCounts(BaseModel):
    """How many executions are in each status, one field per status.

    The fields are exactly the domain's ``ExecutionStatus`` values (a test pins
    that), so every execution lands in exactly one field and the fields sum to
    the number of executions. ``completed_workflows``/``failed_workflows``
    alone left cancelled, interrupted and running runs invisible on the
    dashboard. There is no ``paused``: that word was deleted from orchestration.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    not_started: int = 0
    running: int = 0
    completed: int = 0
    failed: int = 0
    cancelled: int = 0
    interrupted: int = 0


class MetricsResponse(BaseModel):
    """Aggregated metrics response."""

    total_workflows: int = 0
    completed_workflows: int = 0
    failed_workflows: int = 0
    execution_status_counts: ExecutionStatusCounts = Field(default_factory=ExecutionStatusCounts)
    """Executions tallied by status, from the same read model the execution list
    counts its ``status_counts`` facet over, narrowed to ``workflow_id`` when given."""
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


@dataclass(frozen=True)
class _PhaseCost:
    """One phase's cost across a workflow's executions, with its coverage."""

    cost_usd: Decimal
    unpriced_observation_count: int


async def _phase_costs(execution_ids: set[str]) -> dict[str, _PhaseCost]:
    """Per-phase cost summed across ``execution_ids``, keyed by phase id.

    The same source and the same fields the execution detail page reads
    (``cost_by_phase`` / ``unpriced_by_phase``), so the workflow view and the
    execution view cannot disagree about what a phase cost.

    Raises:
        MetricsUnavailableError: the costs could not be read. Deliberately not
            an empty mapping, which would render every phase as ``$0``.
    """
    if not execution_ids:
        return {}
    try:
        costs = await get_execution_cost_query().list_for_ids(execution_ids)
    except Exception as exc:
        logger.warning("Failed to read per-phase execution costs", exc_info=True)
        raise MetricsUnavailableError(
            "phase costs are unavailable: the observability store could not be read"
        ) from exc

    cost_by_phase: dict[str, Decimal] = {}
    unpriced_by_phase: dict[str, int] = {}
    for execution in costs:
        for phase_id, cost in execution.cost_by_phase.items():
            cost_by_phase[phase_id] = cost_by_phase.get(phase_id, Decimal("0")) + cost
        for phase_id, count in execution.unpriced_by_phase.items():
            unpriced_by_phase[phase_id] = unpriced_by_phase.get(phase_id, 0) + count
    return {
        phase_id: _PhaseCost(
            cost_usd=canonical_cost_usd(cost_by_phase.get(phase_id, Decimal("0"))),
            unpriced_observation_count=unpriced_by_phase.get(phase_id, 0),
        )
        for phase_id in cost_by_phase.keys() | unpriced_by_phase.keys()
    }


_NO_PHASE_COST = _PhaseCost(cost_usd=Decimal("0"), unpriced_observation_count=0)


async def _build_phase_metrics(workflow_id: str, execution_ids: set[str]) -> list[PhaseMetrics]:
    """Per-phase metrics: tokens and durations from the projection, cost from Lane 2.

    A failure to read the phase projection degrades to no phases (the
    pre-existing behaviour). A failure to read COSTS does not: it raises
    ``MetricsUnavailableError`` like the totals do, because a phase list whose
    every cost is ``$0`` reads as fact.

    Raises:
        MetricsUnavailableError: the phase costs could not be read.
    """
    costs = await _phase_costs(execution_ids)
    await ensure_connected()
    try:
        manager = get_projection_mgr()
        phases = await manager.workflow_phase_metrics.get_phase_metrics(workflow_id)
        return [
            PhaseMetrics(
                phase_id=phase.phase_id,
                phase_name=phase.phase_name,
                status=phase.status,
                input_tokens=phase.input_tokens,
                output_tokens=phase.output_tokens,
                total_tokens=phase.total_tokens,
                cost_usd=costs.get(phase.phase_id, _NO_PHASE_COST).cost_usd,
                unpriced_observation_count=costs.get(
                    phase.phase_id, _NO_PHASE_COST
                ).unpriced_observation_count,
                cost_in_progress=bool(phase.active_runs),
                # Resolved at read time, by the phase itself: a running phase
                # has no recorded duration to read back, and the 0.0 this used
                # to pass through was the projection's seed value, not a
                # measurement of anything.
                duration_seconds=phase.duration_seconds(),
                artifact_count=phase.artifact_count,
            )
            for phase in phases.values()
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


async def _workflow_execution_ids(workflow_id: str) -> set[str]:
    """Every execution id of one workflow, read once and shared by totals and phases.

    Raises:
        MetricsUnavailableError: the execution list could not be read.
    """
    try:
        manager = get_projection_mgr()
        summaries = await manager.workflow_execution_list.get_by_workflow_id(workflow_id)
    except Exception as exc:
        logger.warning("Failed to read executions for workflow %s", workflow_id, exc_info=True)
        raise MetricsUnavailableError(
            "usage totals are unavailable: the workflow's executions could not be read"
        ) from exc
    return {s.workflow_execution_id for s in summaries}


async def _execution_status_counts(workflow_id: str | None) -> ExecutionStatusCounts:
    """Executions by status, tallied exactly as the execution list tallies its facets.

    Raises:
        MetricsUnavailableError: the execution list could not be read, or it
            holds a status the domain does not define. Dropping such a row
            would make the slices stop summing to the executions that exist.
    """
    try:
        projection = get_projection_mgr().workflow_execution_list
        if workflow_id:
            rows = await projection.get_by_workflow_id(workflow_id)
            counts = Page.unpaged(rows, status_of=lambda s: s.status).status_counts
        else:
            counts = (await projection.page(limit=0)).status_counts
        return ExecutionStatusCounts.model_validate(counts)
    except Exception as exc:
        logger.warning("Failed to count executions by status", exc_info=True)
        raise MetricsUnavailableError(
            "execution status counts are unavailable: the execution list could not be read"
        ) from exc


async def _canonical_totals(execution_ids: set[str] | None) -> CanonicalTotals:
    """Canonical token/cost totals, narrowed to a set of executions when given.

    Raises:
        MetricsUnavailableError: the totals could not be read.
    """
    try:
        query_svc = get_canonical_usage_query()
        if execution_ids is None:
            return await query_svc.totals()
        return await query_svc.totals(execution_ids=execution_ids)
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

    # Tokens, cost and session count come from the ONE canonical definition, the same
    # one the activity heatmap reads (#932). They previously came from Lane 1
    # SessionCompleted events while the heatmap read Lane 2 observations, so
    # the two cards quoted 9,151,116 tokens beside 10,002,629 for the same
    # reality. Workflow/artifact counts stay on the projection: those are
    # domain lifecycle facts, not observed telemetry.
    try:
        status_counts = await _execution_status_counts(workflow_id)
        if workflow_id:
            execution_ids = await _workflow_execution_ids(workflow_id)
            totals = await _canonical_totals(execution_ids)
            phases = await _build_phase_metrics(workflow_id, execution_ids)
        else:
            totals = await _canonical_totals(None)
            phases = []
    except MetricsUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return MetricsResponse(
        total_workflows=m.total_workflows,
        completed_workflows=m.completed_workflows,
        failed_workflows=m.failed_workflows,
        execution_status_counts=status_counts,
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


@router.get("/phase-profiles", response_model=PhaseProfilesResponse)
async def get_phase_profiles_endpoint(
    workflow_id: str = Query(..., description="Workflow whose phases to profile"),
    window_days: int = Query(7, ge=1, le=90, description="Look-back window in days"),
) -> PhaseProfilesResponse:
    """Per phase type and model: p50/p90 tokens and cost; per phase type: p50/p95 resources.

    Sizes the capacity model and the execution budget from what phases of
    this workflow actually used (#1716). Every percentile is over every phase
    in the window; below ten phases it reads ``insufficient``.
    """
    await ensure_connected()
    try:
        execution_ids = await _workflow_execution_ids(workflow_id)
        profiles = await get_phase_profile_query().profiles(
            workflow_id, execution_ids, timedelta(days=window_days)
        )
    except MetricsUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        logger.warning("Failed to read phase profiles for %s", workflow_id, exc_info=True)
        raise HTTPException(
            status_code=503,
            detail="phase profiles are unavailable: the observability store could not be read",
        ) from exc
    return PhaseProfilesResponse.from_profiles(profiles, window_days)


def get_shipped_metrics_query() -> ShippedMetricsQueryService:
    """The process-wide shipped read service (rollup rows behind a cache)."""
    return shipped_metrics_service()


@router.get("/shipped", response_model=ShippedMetricsResponse)
async def get_shipped_metrics_endpoint(
    days: int = Query(
        14,
        description="Window length in UTC days: 7, 14 or 30",
        json_schema_extra={"enum": sorted(SHIPPED_WINDOW_DAYS)},
    ),
    workflow_id: str | None = Query(None, description="Only commits of this workflow's executions"),
) -> ShippedMetricsResponse:
    """What agents shipped over the last ``days`` UTC days, against the ``days`` before.

    Agent-attributed only, read from the shipped ledger's daily rollup: commits
    runs made, PRs runs created (a successful ``gh pr create``), merges of
    those PRs (``pull_request`` closed+merged events from the GitHub
    pipeline), merge rate as the share of the window's opened PRs merged by
    now, and the repos all of that touched.
    """
    if days not in SHIPPED_WINDOW_DAYS:
        allowed = ", ".join(str(d) for d in sorted(SHIPPED_WINDOW_DAYS))
        raise HTTPException(status_code=422, detail=f"days must be one of {allowed}")
    await ensure_connected()
    try:
        metrics = await get_shipped_metrics_query().shipped(days=days, workflow_id=workflow_id)
    except Exception as exc:
        logger.warning("Failed to read shipped metrics", exc_info=True)
        raise HTTPException(
            status_code=503,
            detail="shipped metrics are unavailable: the observability store could not be read",
        ) from exc
    return ShippedMetricsResponse.from_metrics(metrics)
