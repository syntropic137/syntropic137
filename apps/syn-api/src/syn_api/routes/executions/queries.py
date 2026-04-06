"""Execution query endpoints and service functions."""

from __future__ import annotations

import contextlib
import logging
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

from .models import (
    ExecutionDetailResponse,
    ExecutionListResponse,
    ExecutionSummaryResponse,
    PhaseExecutionInfo,
    PhaseOperationInfo,
)

if TYPE_CHECKING:
    from syn_adapters.projections.manager import ProjectionManager
    from syn_api.auth import AuthContext
    from syn_domain.contexts.orchestration.domain.read_models.workflow_execution_detail import (
        PhaseExecutionDetail,
    )

logger = logging.getLogger(__name__)
router = APIRouter(tags=["executions"])


# -- Helpers ------------------------------------------------------------------


def _to_str(val: object | None) -> str | None:
    return str(val) if val is not None else None


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
        return [
            ToolOperation(
                observation_id=op.observation_id,
                operation_type=op.operation_type,
                timestamp=op.timestamp,
                duration_ms=op.duration_ms,
                success=op.success,
                tool_name=op.tool_name,
                tool_use_id=op.tool_use_id,
            )
            for op in (tool_data or [])
        ]
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
        cost_usd=Decimal(str(phase.cost_usd)),
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
    auth: AuthContext | None = None,
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
                total_cost_usd=s.total_cost_usd,
                tool_call_count=tool_counts.get(s.workflow_execution_id, 0),
                error_message=s.error_message,
            )
            for s in domain_summaries
        ]
    )


async def get(
    execution_id: str,
    auth: AuthContext | None = None,
) -> Result[ExecutionDetail, ExecutionError]:
    await ensure_connected()
    manager = get_projection_mgr()
    detail = await manager.workflow_execution_detail.get_by_id(execution_id)
    if detail is None:
        return Err(ExecutionError.NOT_FOUND, message=f"Execution {execution_id} not found")

    # Enrich with TimescaleDB cost data when available (#505)
    total_input = detail.total_input_tokens
    total_output = detail.total_output_tokens
    total_cost = detail.total_cost_usd
    total_duration = detail.total_duration_seconds

    with contextlib.suppress(Exception):
        exec_cost = await manager.execution_cost.get_execution_cost(execution_id)
        if exec_cost is not None and exec_cost.total_tokens > 0:
            total_input = exec_cost.input_tokens
            total_output = exec_cost.output_tokens
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
            total_cost_usd=total_cost,
            total_duration_seconds=total_duration,
            artifact_ids=list(detail.artifact_ids),
            error_message=detail.error_message,
        )
    )


async def get_detail(
    execution_id: str,
    auth: AuthContext | None = None,
) -> Result[ExecutionDetailFull, ExecutionError]:
    await ensure_connected()
    manager = get_projection_mgr()
    detail = await manager.workflow_execution_detail.get_by_id(execution_id)
    if detail is None:
        return Err(ExecutionError.NOT_FOUND, message=f"Execution {execution_id} not found")
    phases = [await _map_phase_detail(p, manager) for p in detail.phases]

    # Enrich with TimescaleDB cost data when available (#505)
    total_tokens = detail.total_input_tokens + detail.total_output_tokens
    total_cost = detail.total_cost_usd

    try:
        exec_cost = await manager.execution_cost.get_execution_cost(execution_id)
        if exec_cost is not None and exec_cost.total_tokens > 0:
            total_tokens = exec_cost.total_tokens
            total_cost = exec_cost.total_cost_usd
    except Exception:
        logger.debug("Failed to load execution cost for %s", execution_id, exc_info=True)

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
        )
    )


async def list_active(
    limit: int = 50,
    auth: AuthContext | None = None,
) -> Result[list[ExecutionSummary], ExecutionError]:
    """List currently running or paused executions."""
    await ensure_connected()
    all_execs = await get_projection_mgr().workflow_execution_list.get_all(
        limit=limit,
        status_filter=None,
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
                total_cost_usd=s.total_cost_usd,
                error_message=s.error_message,
            )
            for s in all_execs
            if s.status in ("running", "paused", "pending")
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
    return ExecutionListResponse(
        executions=[
            ExecutionSummaryResponse(
                workflow_execution_id=e.workflow_execution_id,
                workflow_id=e.workflow_id,
                workflow_name=e.workflow_name,
                status=e.status,
                started_at=_to_str(e.started_at),
                completed_at=_to_str(e.completed_at),
                completed_phases=e.completed_phases,
                total_phases=e.total_phases,
                total_tokens=e.total_tokens,
                total_cost_usd=Decimal(str(e.total_cost_usd)),
                tool_call_count=e.tool_call_count,
                error_message=e.error_message,
            )
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
        cache_creation_tokens=total_cache_creation,
        cache_read_tokens=total_cache_read,
        total_tokens=max(
            detail.total_tokens,
            total_input + total_output + total_cache_creation + total_cache_read,
        ),
        total_cost_usd=Decimal(str(detail.total_cost_usd)),
        artifact_ids=artifact_ids,
        error_message=detail.error_message,
    )
