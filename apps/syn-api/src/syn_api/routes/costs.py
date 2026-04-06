"""Cost tracking API endpoints and service operations.

Provides session-level and execution-level cost tracking with breakdowns.

All cost reads go through CostQueryService (TimescaleDB) — NOT the projection
store, which is empty for cost data. See #532 for the architectural rationale.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from syn_api._wiring import ensure_connected, get_execution_cost_query, get_session_cost_query
from syn_api.types import (
    CostSummary,
    Err,
    ExecutionCostData,
    MetricsError,
    Ok,
    Result,
    SessionCostData,
)

if TYPE_CHECKING:
    from syn_api.auth import AuthContext

router = APIRouter(prefix="/costs", tags=["costs"])


# =============================================================================
# Response Models
# =============================================================================


class SessionCostResponse(BaseModel):
    """Cost for a single session."""

    session_id: str
    execution_id: str | None = None
    workflow_id: str | None = None
    phase_id: str | None = None
    workspace_id: str | None = None
    total_cost_usd: Decimal = Decimal("0")
    token_cost_usd: Decimal = Decimal("0")
    compute_cost_usd: Decimal = Decimal("0")
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0
    tool_calls: int = 0
    turns: int = 0
    duration_ms: float = 0
    cost_by_model: dict[str, str] = Field(default_factory=dict)
    cost_by_tool: dict[str, str] = Field(default_factory=dict)
    tokens_by_tool: dict[str, int] = Field(default_factory=dict)
    cost_by_tool_tokens: dict[str, str] = Field(default_factory=dict)
    is_finalized: bool = False
    started_at: str | None = None
    completed_at: str | None = None


class ExecutionCostResponse(BaseModel):
    """Aggregated cost for a workflow execution."""

    execution_id: str
    workflow_id: str | None = None
    session_count: int = 0
    session_ids: list[str] = Field(default_factory=list)
    total_cost_usd: Decimal = Decimal("0")
    token_cost_usd: Decimal = Decimal("0")
    compute_cost_usd: Decimal = Decimal("0")
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0
    tool_calls: int = 0
    turns: int = 0
    duration_ms: float = 0
    cost_by_phase: dict[str, str] = Field(default_factory=dict)
    cost_by_model: dict[str, str] = Field(default_factory=dict)
    cost_by_tool: dict[str, str] = Field(default_factory=dict)
    is_complete: bool = False
    started_at: str | None = None
    completed_at: str | None = None


class CostSummaryResponse(BaseModel):
    """Summary of all costs across sessions/executions."""

    total_cost_usd: Decimal = Decimal("0")
    total_sessions: int = 0
    total_executions: int = 0
    total_tokens: int = 0
    total_tool_calls: int = 0
    top_models: list[dict[str, Any]] = Field(default_factory=list)
    top_sessions: list[dict[str, Any]] = Field(default_factory=list)


# =============================================================================
# Service functions (importable by tests)
# =============================================================================


async def list_session_costs(
    execution_id: str | None = None,
    limit: int = 100,
    auth: AuthContext | None = None,  # noqa: ARG001
) -> Result[list[SessionCostData], MetricsError]:
    """List cost data for sessions.

    Uses SessionCostQueryService (TimescaleDB) for reads. See #532.

    Args:
        execution_id: Optional filter by execution ID. Applied client-side
            because execution_id is a grouping dimension, not a primary filter
            in the aggregate queries. For small result sets this is adequate.
        limit: Maximum results to return (pushed down to SQL).
        auth: Optional authentication context.
    """
    await ensure_connected()
    try:
        query_svc = get_session_cost_query()
        all_costs = await query_svc.list_all(limit=limit)

        costs = (
            [c for c in all_costs if c.execution_id == execution_id] if execution_id else all_costs
        )

        return Ok(
            [
                SessionCostData(
                    session_id=c.session_id,
                    execution_id=c.execution_id,
                    workflow_id=c.workflow_id,
                    phase_id=c.phase_id,
                    total_cost_usd=Decimal(str(c.total_cost_usd)),
                    token_cost_usd=Decimal(str(c.token_cost_usd)),
                    input_tokens=c.input_tokens,
                    output_tokens=c.output_tokens,
                    total_tokens=c.total_tokens,
                    cache_creation_tokens=c.cache_creation_tokens,
                    cache_read_tokens=c.cache_read_tokens,
                    tool_calls=c.tool_calls,
                    turns=c.turns,
                    duration_ms=int(c.duration_ms),
                    cost_by_model=c.cost_by_model,
                    cost_by_tool=c.cost_by_tool,
                    is_finalized=c.is_finalized,
                    started_at=c.started_at,
                    completed_at=c.completed_at,
                )
                for c in costs
            ]
        )
    except Exception as e:
        return Err(MetricsError.QUERY_FAILED, message=str(e))


async def get_session_cost(
    session_id: str,
    include_breakdown: bool = False,  # noqa: ARG001
    auth: AuthContext | None = None,  # noqa: ARG001
) -> Result[SessionCostData, MetricsError]:
    """Get cost data for a single session.

    Uses SessionCostQueryService (TimescaleDB) for reads. See #532.

    Args:
        session_id: The session ID.
        include_breakdown: Whether to include model/tool breakdowns.
        auth: Optional authentication context.
    """
    await ensure_connected()
    try:
        query_svc = get_session_cost_query()
        c = await query_svc.get(session_id)

        if c is None:
            return Err(MetricsError.NOT_FOUND, message=f"Session {session_id} not found")

        return Ok(
            SessionCostData(
                session_id=c.session_id,
                execution_id=c.execution_id,
                workflow_id=c.workflow_id,
                phase_id=c.phase_id,
                total_cost_usd=Decimal(str(c.total_cost_usd)),
                token_cost_usd=Decimal(str(c.token_cost_usd)),
                input_tokens=c.input_tokens,
                output_tokens=c.output_tokens,
                total_tokens=c.total_tokens,
                cache_creation_tokens=c.cache_creation_tokens,
                cache_read_tokens=c.cache_read_tokens,
                tool_calls=c.tool_calls,
                turns=c.turns,
                duration_ms=int(c.duration_ms),
                cost_by_model=c.cost_by_model,
                cost_by_tool=c.cost_by_tool,
                is_finalized=c.is_finalized,
                started_at=c.started_at,
                completed_at=c.completed_at,
            )
        )
    except Exception as e:
        return Err(MetricsError.QUERY_FAILED, message=str(e))


async def list_execution_costs(
    limit: int = 100,
    auth: AuthContext | None = None,  # noqa: ARG001
) -> Result[list[ExecutionCostData], MetricsError]:
    """List cost data for executions.

    Uses ExecutionCostQueryService (TimescaleDB) for reads. See #532.

    Args:
        limit: Maximum results to return.
        auth: Optional authentication context.
    """
    await ensure_connected()
    try:
        query_svc = get_execution_cost_query()
        costs = await query_svc.list_all(limit=limit)

        return Ok(
            [
                ExecutionCostData(
                    execution_id=c.execution_id,
                    workflow_id=c.workflow_id,
                    session_count=c.session_count,
                    session_ids=c.session_ids,
                    total_cost_usd=Decimal(str(c.total_cost_usd)),
                    input_tokens=c.input_tokens,
                    output_tokens=c.output_tokens,
                    total_tokens=c.total_tokens,
                    cost_by_phase=c.cost_by_phase,
                    cost_by_model=c.cost_by_model,
                    cost_by_tool=c.cost_by_tool,
                    is_complete=c.is_complete,
                    started_at=c.started_at,
                    completed_at=c.completed_at,
                )
                for c in (costs or [])[:limit]
            ]
        )
    except Exception as e:
        return Err(MetricsError.QUERY_FAILED, message=str(e))


async def get_execution_cost(
    execution_id: str,
    include_breakdown: bool = False,  # noqa: ARG001
    auth: AuthContext | None = None,  # noqa: ARG001
) -> Result[ExecutionCostData, MetricsError]:
    """Get cost data for a single execution.

    Uses ExecutionCostQueryService (TimescaleDB) for reads. See #532.

    Args:
        execution_id: The execution ID.
        include_breakdown: Whether to include phase/model/tool breakdowns.
        auth: Optional authentication context.
    """
    await ensure_connected()
    try:
        query_svc = get_execution_cost_query()
        c = await query_svc.get(execution_id)

        if c is None:
            return Err(MetricsError.NOT_FOUND, message=f"Execution {execution_id} not found")

        return Ok(
            ExecutionCostData(
                execution_id=c.execution_id,
                workflow_id=c.workflow_id,
                session_count=c.session_count,
                session_ids=c.session_ids,
                total_cost_usd=Decimal(str(c.total_cost_usd)),
                input_tokens=c.input_tokens,
                output_tokens=c.output_tokens,
                total_tokens=c.total_tokens,
                cost_by_phase=c.cost_by_phase,
                cost_by_model=c.cost_by_model,
                cost_by_tool=c.cost_by_tool,
                is_complete=c.is_complete,
                started_at=c.started_at,
                completed_at=c.completed_at,
            )
        )
    except Exception as e:
        return Err(MetricsError.QUERY_FAILED, message=str(e))


async def get_cost_summary(
    auth: AuthContext | None = None,  # noqa: ARG001
) -> Result[CostSummary, MetricsError]:
    """Get overall cost summary across all executions.

    Uses ExecutionCostQueryService (TimescaleDB) for reads. See #532.

    Args:
        auth: Optional authentication context.
    """
    await ensure_connected()
    try:
        query_svc = get_execution_cost_query()
        all_costs = await query_svc.list_all()

        total_cost = Decimal(str(sum(c.total_cost_usd for c in (all_costs or []))))
        total_tokens = sum(c.total_tokens for c in (all_costs or []))
        total_sessions = sum(c.session_count for c in (all_costs or []))
        total_tool_calls = sum(c.tool_calls for c in (all_costs or []))

        return Ok(
            CostSummary(
                total_cost_usd=total_cost,
                total_sessions=total_sessions,
                total_executions=len(all_costs or []),
                total_tokens=total_tokens,
                total_tool_calls=total_tool_calls,
                top_models=[],
                top_sessions=[],
            )
        )
    except Exception as e:
        return Err(MetricsError.QUERY_FAILED, message=str(e))


# =============================================================================
# Helpers
# =============================================================================


def _session_cost_to_api(c: Any) -> SessionCostResponse:  # noqa: ANN401
    """Convert syn_api SessionCostData to SessionCostResponse."""
    return SessionCostResponse(
        session_id=c.session_id,
        execution_id=c.execution_id,
        workflow_id=c.workflow_id,
        phase_id=c.phase_id,
        total_cost_usd=Decimal(str(c.total_cost_usd)),
        token_cost_usd=Decimal(str(c.token_cost_usd)),
        input_tokens=c.input_tokens,
        output_tokens=c.output_tokens,
        total_tokens=c.total_tokens,
        cache_creation_tokens=c.cache_creation_tokens,
        cache_read_tokens=c.cache_read_tokens,
        tool_calls=c.tool_calls,
        turns=c.turns,
        duration_ms=c.duration_ms,
        cost_by_model={k: str(v) for k, v in (c.cost_by_model or {}).items()},
        cost_by_tool={k: str(v) for k, v in (c.cost_by_tool or {}).items()},
        is_finalized=c.is_finalized,
        started_at=str(c.started_at) if c.started_at else None,
        completed_at=str(c.completed_at) if c.completed_at else None,
    )


def _execution_cost_to_api(c: Any) -> ExecutionCostResponse:  # noqa: ANN401
    """Convert syn_api ExecutionCostData to ExecutionCostResponse."""
    return ExecutionCostResponse(
        execution_id=c.execution_id,
        workflow_id=c.workflow_id,
        session_count=c.session_count,
        session_ids=c.session_ids or [],
        total_cost_usd=Decimal(str(c.total_cost_usd)),
        input_tokens=c.input_tokens,
        output_tokens=c.output_tokens,
        total_tokens=c.total_tokens,
        cost_by_phase={k: str(v) for k, v in (c.cost_by_phase or {}).items()},
        cost_by_model={k: str(v) for k, v in (c.cost_by_model or {}).items()},
        cost_by_tool={k: str(v) for k, v in (c.cost_by_tool or {}).items()},
        is_complete=c.is_complete,
        started_at=str(c.started_at) if c.started_at else None,
        completed_at=str(c.completed_at) if c.completed_at else None,
    )


# =============================================================================
# HTTP Endpoints
# =============================================================================


@router.get("/sessions", response_model=list[SessionCostResponse])
async def list_session_costs_endpoint(
    execution_id: str | None = Query(None, description="Filter by execution ID"),
    limit: int = Query(50, ge=1, le=200, description="Max items to return"),
) -> list[SessionCostResponse]:
    """List session costs with optional filtering."""
    result = await list_session_costs(execution_id=execution_id, limit=limit)

    if isinstance(result, Err):
        raise HTTPException(status_code=500, detail=result.message)

    return [_session_cost_to_api(s) for s in result.value]


@router.get("/sessions/{session_id}", response_model=SessionCostResponse)
async def get_session_cost_endpoint(
    session_id: str,
    include_breakdown: bool = Query(True, description="Include model/tool breakdowns"),
) -> SessionCostResponse:
    """Get cost for a specific session."""
    from syn_api._wiring import get_projection_mgr
    from syn_api.prefix_resolver import resolve_or_raise

    mgr = get_projection_mgr()
    session_id = await resolve_or_raise(mgr.store, "session_summaries", session_id, "Session")
    result = await get_session_cost(session_id, include_breakdown=include_breakdown)

    if isinstance(result, Err):
        raise HTTPException(
            status_code=404,
            detail=f"Session cost not found for session {session_id}",
        )

    response = _session_cost_to_api(result.value)
    if not include_breakdown:
        response.cost_by_model = {}
        response.cost_by_tool = {}

    return response


@router.get("/executions", response_model=list[ExecutionCostResponse])
async def list_execution_costs_endpoint(
    limit: int = Query(50, ge=1, le=200, description="Max items to return"),
) -> list[ExecutionCostResponse]:
    """List execution costs."""
    result = await list_execution_costs(limit=limit)

    if isinstance(result, Err):
        raise HTTPException(status_code=500, detail=result.message)

    return [_execution_cost_to_api(e) for e in result.value]


@router.get("/executions/{execution_id}", response_model=ExecutionCostResponse)
async def get_execution_cost_endpoint(
    execution_id: str,
    include_breakdown: bool = Query(True, description="Include phase/model/tool breakdowns"),
    include_session_ids: bool = Query(False, description="Include list of session IDs"),
) -> ExecutionCostResponse:
    """Get aggregated cost for a workflow execution."""
    from syn_api._wiring import get_projection_mgr
    from syn_api.prefix_resolver import resolve_or_raise

    mgr = get_projection_mgr()
    execution_id = await resolve_or_raise(
        mgr.store, "workflow_execution_details", execution_id, "Execution"
    )
    result = await get_execution_cost(execution_id, include_breakdown=include_breakdown)

    if isinstance(result, Err):
        raise HTTPException(
            status_code=404,
            detail=f"Execution cost not found for execution {execution_id}",
        )

    response = _execution_cost_to_api(result.value)
    if not include_breakdown:
        response.cost_by_phase = {}
        response.cost_by_model = {}
        response.cost_by_tool = {}

    if not include_session_ids:
        response.session_ids = []

    return response


@router.get("/summary", response_model=CostSummaryResponse)
async def get_cost_summary_endpoint() -> CostSummaryResponse:
    """Get summary of all costs across sessions and executions."""
    result = await get_cost_summary()

    if isinstance(result, Err):
        return CostSummaryResponse()

    s = result.value
    return CostSummaryResponse(
        total_cost_usd=Decimal(str(s.total_cost_usd)),
        total_sessions=s.total_sessions,
        total_executions=s.total_executions,
        total_tokens=s.total_tokens,
        total_tool_calls=s.total_tool_calls,
        top_models=s.top_models,
        top_sessions=s.top_sessions,
    )
