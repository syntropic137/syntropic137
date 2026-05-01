"""Execution query endpoints and service functions."""

from __future__ import annotations

import contextlib
import logging
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, NamedTuple

from fastapi import APIRouter, HTTPException, Query

from syn_api._wiring import ensure_connected, get_projection_mgr
from syn_api.types import (
    Err,
    ExecutionDetail,
    ExecutionDetailFull,
    ExecutionError,
    ExecutionSummary,
    Ok,
    PhaseExecution,
    Result,
    ToolOperation,
)
from syn_shared.display import (
    format_cost,
    format_duration_seconds,
    format_repos,
    format_tokens,
)

from .models import (
    ExecutionDetailResponse,
    ExecutionListResponse,
    ExecutionSummaryResponse,
    PhaseExecutionInfo,
    PhaseOperationInfo,
)

if TYPE_CHECKING:
    from syn_adapters.projections.manager import ProjectionManager
    from syn_domain.contexts.orchestration.domain.read_models.workflow_execution_detail import (
        PhaseExecutionDetail,
    )

logger = logging.getLogger(__name__)
router = APIRouter(tags=["executions"])


# -- Helpers ------------------------------------------------------------------


def _to_str(val: object | None) -> str | None:
    return str(val) if val is not None else None


def _coerce_dt(value: object | None) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        with contextlib.suppress(ValueError):
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
    return None


def _duration_seconds(started: object | None, completed: object | None) -> float | None:
    """Compute duration from start/end timestamps when both are present."""
    s = _coerce_dt(started)
    c = _coerce_dt(completed)
    if s is None or c is None:
        return None
    return (c - s).total_seconds()


@dataclass
class _MergedExecutionTotals:
    """Token + cost totals after preferring Lane 2 enrichment over domain values."""

    cost: Decimal
    input_tokens: int
    output_tokens: int
    cache_creation_tokens: int
    cache_read_tokens: int
    total_tokens: int


def _merge_totals(
    e: ExecutionSummary, enrichment: _ExecutionEnrichment | None
) -> _MergedExecutionTotals:
    """Prefer Lane 2 totals when present; fall back to the domain summary."""
    if enrichment is None:
        return _MergedExecutionTotals(
            cost=Decimal(str(e.total_cost_usd)),
            input_tokens=e.total_input_tokens,
            output_tokens=e.total_output_tokens,
            cache_creation_tokens=e.total_cache_creation_tokens,
            cache_read_tokens=e.total_cache_read_tokens,
            total_tokens=e.total_tokens,
        )
    return _MergedExecutionTotals(
        cost=enrichment.total_cost_usd,
        input_tokens=enrichment.input_tokens
        if enrichment.input_tokens is not None
        else e.total_input_tokens,
        output_tokens=enrichment.output_tokens
        if enrichment.output_tokens is not None
        else e.total_output_tokens,
        cache_creation_tokens=enrichment.cache_creation_tokens
        if enrichment.cache_creation_tokens is not None
        else e.total_cache_creation_tokens,
        cache_read_tokens=enrichment.cache_read_tokens
        if enrichment.cache_read_tokens is not None
        else e.total_cache_read_tokens,
        total_tokens=enrichment.total_tokens
        if enrichment.total_tokens is not None
        else e.total_tokens,
    )


def _build_execution_summary_response(
    e: ExecutionSummary,
    enrichment: _ExecutionEnrichment | None = None,
) -> ExecutionSummaryResponse:
    """Compose an ExecutionSummaryResponse from a domain summary + enrichment.

    Token + cost totals prefer Lane 2 (live) over the domain projection,
    which only finalizes on phase completion. Display fields are derived
    from raw values via syn_shared.display so all clients (dashboard,
    CLI) share identical strings.
    """
    duration_seconds = _duration_seconds(e.started_at, e.completed_at)
    totals = _merge_totals(e, enrichment)
    return ExecutionSummaryResponse(
        workflow_execution_id=e.workflow_execution_id,
        workflow_id=e.workflow_id,
        workflow_name=e.workflow_name,
        status=e.status,
        started_at=_to_str(e.started_at),
        completed_at=_to_str(e.completed_at),
        completed_phases=e.completed_phases,
        total_phases=e.total_phases,
        total_tokens=totals.total_tokens,
        total_tokens_display=format_tokens(totals.total_tokens),
        total_input_tokens=totals.input_tokens,
        total_output_tokens=totals.output_tokens,
        total_cache_creation_tokens=totals.cache_creation_tokens,
        total_cache_read_tokens=totals.cache_read_tokens,
        total_cost_usd=totals.cost,
        total_cost_display=format_cost(totals.cost),
        duration_seconds=duration_seconds,
        duration_display=format_duration_seconds(duration_seconds),
        tool_call_count=e.tool_call_count,
        error_message=e.error_message,
        repos=list(e.repos),
        repos_display=format_repos(e.repos),
    )


def _parse_iso(value: str) -> datetime | None:
    """Parse an ISO datetime string, handling trailing 'Z' safely."""
    raw = value.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        logger.warning("Failed to parse datetime from value %r", value)
        return None


def _parse_dt(value: datetime | str | None) -> datetime | None:
    """Normalise a datetime-or-string field to datetime."""
    if value is None:
        return None
    return _parse_iso(value) if isinstance(value, str) else value


async def _load_phase_operations(
    manager: ProjectionManager,
    session_id: str,
) -> list[ToolOperation]:
    """Load tool operations for a session, returning [] on failure."""
    try:
        tool_data = await manager.session_tools.get(session_id)
        return [ToolOperation.model_validate(op, from_attributes=True) for op in (tool_data or [])]
    except Exception:
        logger.exception("Failed to load tool ops for session %s", session_id)
        return []


class _SessionCostData(NamedTuple):
    cache_creation: int
    cache_read: int
    agent_model: str | None
    cost_by_model: dict[str, Decimal]


async def _load_session_cost(
    manager: ProjectionManager, session_id: str, phase: PhaseExecutionDetail
) -> _SessionCostData:
    """Load session cost enrichment data (cache tokens, model info)."""
    cache_creation = phase.cache_creation_tokens
    cache_read = phase.cache_read_tokens
    agent_model: str | None = None
    cost_by_model: dict[str, Decimal] = {}
    try:
        sc = await manager.session_cost.get_session_cost(session_id)
        if sc is not None:
            if cache_creation == 0 and cache_read == 0:
                cache_creation = sc.cache_creation_tokens
                cache_read = sc.cache_read_tokens
            agent_model = sc.agent_model
            cost_by_model = dict(sc.cost_by_model)
    except Exception:
        logger.debug("Failed to load session cost for %s", session_id, exc_info=True)
    return _SessionCostData(cache_creation, cache_read, agent_model, cost_by_model)


async def _map_phase_detail(
    phase: PhaseExecutionDetail,
    manager: ProjectionManager,
) -> PhaseExecution:
    """Map a domain phase to an API PhaseExecution."""
    ops = await _load_phase_operations(manager, phase.session_id) if phase.session_id else []

    if phase.session_id:
        sc = await _load_session_cost(manager, phase.session_id, phase)
    else:
        sc = _SessionCostData(phase.cache_creation_tokens, phase.cache_read_tokens, None, {})

    return PhaseExecution(
        phase_id=phase.workflow_phase_id,
        name=phase.name,
        status=phase.status,
        session_id=phase.session_id,
        artifact_id=phase.artifact_id,
        input_tokens=phase.input_tokens,
        output_tokens=phase.output_tokens,
        cache_creation_tokens=sc.cache_creation,
        cache_read_tokens=sc.cache_read,
        cost_usd=Decimal("0"),  # Lane 2: enriched via _enrich_costs from execution_cost (#695)
        duration_seconds=phase.duration_seconds,
        started_at=_parse_dt(phase.started_at),
        completed_at=_parse_dt(phase.completed_at),
        model=sc.agent_model,
        cost_by_model=sc.cost_by_model,
        operations=ops,
    )


def _map_phase_to_response(phase: PhaseExecution) -> PhaseExecutionInfo:
    """Map an API PhaseExecution to an HTTP response model."""
    operations = [
        PhaseOperationInfo(
            operation_id=op.observation_id,
            operation_type=op.operation_type,
            timestamp=str(op.timestamp) if op.timestamp else None,
            tool_name=op.tool_name,
            tool_use_id=op.tool_use_id,
            success=op.success if op.success is not None else True,
        )
        for op in (phase.operations or [])
    ]
    return PhaseExecutionInfo(
        phase_id=phase.phase_id,
        name=phase.name,
        status=phase.status,
        session_id=phase.session_id,
        artifact_id=phase.artifact_id,
        input_tokens=phase.input_tokens,
        output_tokens=phase.output_tokens,
        cache_creation_tokens=phase.cache_creation_tokens,
        cache_read_tokens=phase.cache_read_tokens,
        total_tokens=phase.input_tokens
        + phase.output_tokens
        + phase.cache_creation_tokens
        + phase.cache_read_tokens,
        duration_seconds=phase.duration_seconds or 0.0,
        cost_usd=Decimal(str(phase.cost_usd)),
        started_at=str(phase.started_at) if phase.started_at else None,
        completed_at=str(phase.completed_at) if phase.completed_at else None,
        model=phase.model,
        cost_by_model={k: str(v) for k, v in phase.cost_by_model.items()},
        operations=operations,
    )


@dataclass
class _ExecutionEnrichment:
    """Per-execution enrichment loaded from Lane 2 (execution_cost projection).

    Lane 2 updates token + cost totals continuously while phases run, so
    these values are live for in-flight executions. The domain projection
    (Lane 1) only sees final tokens on phase completion.
    """

    total_cost_usd: Decimal = Decimal("0")
    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_creation_tokens: int | None = None
    cache_read_tokens: int | None = None
    total_tokens: int | None = None


async def _load_execution_enrichment(
    manager: ProjectionManager, execution_ids: list[str]
) -> dict[str, _ExecutionEnrichment]:
    """Load per-execution enrichment from the Lane 2 execution_cost projection (#695)."""
    out: dict[str, _ExecutionEnrichment] = {}
    for eid in execution_ids:
        try:
            ec = await manager.execution_cost.get_execution_cost(eid)
        except Exception:
            logger.debug("Failed to load execution cost for %s", eid, exc_info=True)
            continue
        if ec is None:
            continue
        total = ec.input_tokens + ec.output_tokens + ec.cache_creation_tokens + ec.cache_read_tokens
        out[eid] = _ExecutionEnrichment(
            total_cost_usd=ec.total_cost_usd,
            input_tokens=ec.input_tokens,
            output_tokens=ec.output_tokens,
            cache_creation_tokens=ec.cache_creation_tokens,
            cache_read_tokens=ec.cache_read_tokens,
            total_tokens=total,
        )
    return out


async def _load_execution_costs(
    manager: ProjectionManager, execution_ids: list[str]
) -> dict[str, Decimal]:
    """Backwards-compat: cost-only view kept for legacy callers."""
    enriched = await _load_execution_enrichment(manager, execution_ids)
    return {eid: e.total_cost_usd for eid, e in enriched.items()}


async def _fetch_tool_counts(execution_ids: list[str]) -> dict[str, int]:
    """Query tool_execution_completed counts from agent_events."""
    try:
        from syn_api._wiring import get_event_store_instance

        event_store = get_event_store_instance()
        pool = event_store.pool
        if pool is None:
            return {}
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT execution_id, COUNT(*) AS cnt "
                "FROM agent_events "
                "WHERE execution_id = ANY($1) "
                "  AND event_type = 'tool_execution_completed' "
                "GROUP BY execution_id",
                execution_ids,
            )
        return {row["execution_id"]: row["cnt"] for row in rows}
    except Exception:
        logger.debug("Could not query tool counts from agent_events", exc_info=True)
        return {}


# -- Service functions --------------------------------------------------------


async def list_(
    workflow_id: str | None = None,
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> Result[list[ExecutionSummary], ExecutionError]:
    await ensure_connected()
    manager = get_projection_mgr()
    projection = manager.workflow_execution_list
    if workflow_id:
        domain_summaries = await projection.get_by_workflow_id(workflow_id)
    else:
        domain_summaries = await projection.get_all(
            limit=limit,
            offset=offset,
            status_filter=status,
        )
    tool_counts = (
        await _fetch_tool_counts([s.workflow_execution_id for s in domain_summaries])
        if domain_summaries
        else {}
    )
    # Enrich each execution's total_cost_usd from the Lane 2 execution_cost projection (#695)
    cost_by_execution = await _load_execution_costs(
        manager, [s.workflow_execution_id for s in domain_summaries]
    )
    return Ok(
        [
            ExecutionSummary(
                workflow_execution_id=s.workflow_execution_id,
                workflow_id=s.workflow_id,
                workflow_name=s.workflow_name,
                status=s.status,
                started_at=s.started_at,
                completed_at=s.completed_at,
                completed_phases=s.completed_phases,
                total_phases=s.total_phases,
                total_tokens=s.total_tokens,
                total_input_tokens=s.total_input_tokens,
                total_output_tokens=s.total_output_tokens,
                total_cache_creation_tokens=s.total_cache_creation_tokens,
                total_cache_read_tokens=s.total_cache_read_tokens,
                total_cost_usd=cost_by_execution.get(s.workflow_execution_id, Decimal("0")),
                tool_call_count=tool_counts.get(s.workflow_execution_id, 0),
                error_message=s.error_message,
                repos=list(s.repos),
            )
            for s in domain_summaries
        ]
    )


async def get(
    execution_id: str,
) -> Result[ExecutionDetail, ExecutionError]:
    await ensure_connected()
    manager = get_projection_mgr()
    detail = await manager.workflow_execution_detail.get_by_id(execution_id)
    if detail is None:
        return Err(ExecutionError.NOT_FOUND, message=f"Execution {execution_id} not found")

    # Enrich with TimescaleDB cost data when available (#505, #695: cost is Lane 2)
    total_input = detail.total_input_tokens
    total_output = detail.total_output_tokens
    total_cache_creation = detail.total_cache_creation_tokens
    total_cache_read = detail.total_cache_read_tokens
    total_cost: Decimal | str = Decimal("0")
    total_duration = detail.total_duration_seconds

    with contextlib.suppress(Exception):
        exec_cost = await manager.execution_cost.get_execution_cost(execution_id)
        if exec_cost is not None and exec_cost.total_tokens > 0:
            total_input = exec_cost.input_tokens
            total_output = exec_cost.output_tokens
            total_cache_creation = exec_cost.cache_creation_tokens or total_cache_creation
            total_cache_read = exec_cost.cache_read_tokens or total_cache_read
            total_cost = exec_cost.total_cost_usd
            if exec_cost.duration_ms > 0:
                total_duration = exec_cost.duration_ms / 1000.0

    return Ok(
        ExecutionDetail(
            workflow_execution_id=detail.workflow_execution_id,
            workflow_id=detail.workflow_id,
            workflow_name=detail.workflow_name,
            status=detail.status,
            started_at=detail.started_at,
            completed_at=detail.completed_at,
            total_input_tokens=total_input,
            total_output_tokens=total_output,
            total_cache_creation_tokens=total_cache_creation,
            total_cache_read_tokens=total_cache_read,
            total_cost_usd=total_cost,
            total_duration_seconds=total_duration,
            artifact_ids=list(detail.artifact_ids),
            error_message=detail.error_message,
            repos=list(detail.repos),
        )
    )


async def _enrich_costs(
    execution_id: str,
    manager: object,
    phases: list[PhaseExecution],
    fallback_tokens: int,
    fallback_cost: Decimal | str,
) -> tuple[int, Decimal | str]:
    """Enrich execution and phase costs from TimescaleDB (#505)."""
    try:
        exec_cost = await manager.execution_cost.get_execution_cost(execution_id)  # type: ignore[attr-defined]
    except Exception:
        logger.debug("Failed to load execution cost for %s", execution_id, exc_info=True)
        return fallback_tokens, fallback_cost

    if exec_cost is None or exec_cost.total_tokens == 0:
        return fallback_tokens, fallback_cost

    if exec_cost.cost_by_phase:
        for phase in phases:
            phase_cost = exec_cost.cost_by_phase.get(phase.phase_id)
            if phase_cost is not None:
                phase.cost_usd = phase_cost

    return exec_cost.total_tokens, exec_cost.total_cost_usd


async def get_detail(
    execution_id: str,
) -> Result[ExecutionDetailFull, ExecutionError]:
    await ensure_connected()
    manager = get_projection_mgr()
    detail = await manager.workflow_execution_detail.get_by_id(execution_id)
    if detail is None:
        return Err(ExecutionError.NOT_FOUND, message=f"Execution {execution_id} not found")
    phases = [await _map_phase_detail(p, manager) for p in detail.phases]

    total_tokens, total_cost = await _enrich_costs(
        execution_id,
        manager,
        phases,
        fallback_tokens=detail.total_input_tokens + detail.total_output_tokens,
        fallback_cost=Decimal("0"),
    )

    return Ok(
        ExecutionDetailFull(
            workflow_execution_id=detail.workflow_execution_id,
            workflow_id=detail.workflow_id,
            workflow_name=detail.workflow_name,
            status=detail.status,
            phases=phases,
            total_tokens=total_tokens,
            total_cost_usd=total_cost,
            started_at=detail.started_at,
            completed_at=detail.completed_at,
            error_message=detail.error_message,
            repos=list(detail.repos),
        )
    )


async def list_active(
    limit: int = 50,
) -> Result[list[ExecutionSummary], ExecutionError]:
    """List currently running or paused executions."""
    await ensure_connected()
    manager = get_projection_mgr()
    all_execs = await manager.workflow_execution_list.get_all(
        limit=limit,
        status_filter=None,
    )
    active = [s for s in all_execs if s.status in ("running", "paused", "pending")]
    # Enrich cost from Lane 2 execution_cost projection (#695)
    cost_by_execution = await _load_execution_costs(
        manager, [s.workflow_execution_id for s in active]
    )
    return Ok(
        [
            ExecutionSummary(
                workflow_execution_id=s.workflow_execution_id,
                workflow_id=s.workflow_id,
                workflow_name=s.workflow_name,
                status=s.status,
                started_at=s.started_at,
                completed_at=s.completed_at,
                completed_phases=s.completed_phases,
                total_phases=s.total_phases,
                total_tokens=s.total_tokens,
                total_cost_usd=cost_by_execution.get(s.workflow_execution_id, Decimal("0")),
                error_message=s.error_message,
                repos=list(s.repos),
            )
            for s in active
        ]
    )


# -- HTTP Endpoints -----------------------------------------------------------


@router.get("/executions", response_model=ExecutionListResponse)
async def list_executions_endpoint(
    status: str | None = Query(None, description="Filter by status"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(50, ge=1, le=100, description="Items per page"),
) -> ExecutionListResponse:
    """List all workflow executions across all workflows."""
    offset = (page - 1) * page_size
    result = await list_(status=status, limit=page_size, offset=offset)
    if isinstance(result, Err):
        raise HTTPException(status_code=500, detail=result.message)
    manager = get_projection_mgr()
    enrichment = await _load_execution_enrichment(
        manager, [e.workflow_execution_id for e in result.value]
    )
    return ExecutionListResponse(
        executions=[
            _build_execution_summary_response(e, enrichment.get(e.workflow_execution_id))
            for e in result.value
        ],
        total=len(result.value),
        page=page,
        page_size=page_size,
    )


@router.get("/executions/{execution_id}", response_model=ExecutionDetailResponse)
async def get_execution_endpoint(execution_id: str) -> ExecutionDetailResponse:
    """Get detailed information about a workflow execution run (supports partial ID prefix matching)."""
    from syn_api._wiring import get_projection_mgr
    from syn_api.prefix_resolver import resolve_or_raise

    mgr = get_projection_mgr()
    execution_id = await resolve_or_raise(
        mgr.store, "workflow_execution_details", execution_id, "Execution"
    )
    result = await get_detail(execution_id)
    if isinstance(result, Err):
        raise HTTPException(status_code=404, detail=f"Execution {execution_id} not found")
    detail = result.value
    phases = [_map_phase_to_response(p) for p in detail.phases or []]
    total_input = sum(p.input_tokens for p in detail.phases or [])
    total_output = sum(p.output_tokens for p in detail.phases or [])
    total_cache_creation = sum(p.cache_creation_tokens for p in phases)
    total_cache_read = sum(p.cache_read_tokens for p in phases)
    artifact_ids = [p.artifact_id for p in phases if p.artifact_id]
    return ExecutionDetailResponse(
        workflow_execution_id=detail.workflow_execution_id,
        workflow_id=detail.workflow_id,
        workflow_name=detail.workflow_name,
        status=detail.status,
        started_at=str(detail.started_at) if detail.started_at else None,
        completed_at=str(detail.completed_at) if detail.completed_at else None,
        phases=phases,
        total_input_tokens=total_input,
        total_output_tokens=total_output,
        total_cache_creation_tokens=total_cache_creation,
        total_cache_read_tokens=total_cache_read,
        total_tokens=max(
            detail.total_tokens,
            total_input + total_output + total_cache_creation + total_cache_read,
        ),
        total_cost_usd=Decimal(str(detail.total_cost_usd)),
        artifact_ids=artifact_ids,
        error_message=detail.error_message,
        repos=list(detail.repos),
    )
