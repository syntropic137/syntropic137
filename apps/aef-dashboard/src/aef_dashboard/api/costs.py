"""Cost tracking API endpoints."""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException, Query

from aef_adapters.projections import get_projection_manager
from aef_dashboard.models.schemas import (
    CostSummaryResponse,
    ExecutionCostResponse,
    SessionCostResponse,
)

if TYPE_CHECKING:
    from aef_domain.contexts.costs.domain.read_models.execution_cost import ExecutionCost
    from aef_domain.contexts.costs.domain.read_models.session_cost import SessionCost

router = APIRouter(prefix="/costs", tags=["costs"])


def _domain_session_cost_to_api(cost: SessionCost) -> SessionCostResponse:
    """Convert domain SessionCost to API SessionCostResponse."""
    return SessionCostResponse(
        session_id=cost.session_id,
        execution_id=cost.execution_id,
        workflow_id=cost.workflow_id,
        phase_id=cost.phase_id,
        workspace_id=cost.workspace_id,
        total_cost_usd=cost.total_cost_usd,
        token_cost_usd=cost.token_cost_usd,
        compute_cost_usd=cost.compute_cost_usd,
        input_tokens=cost.input_tokens,
        output_tokens=cost.output_tokens,
        total_tokens=cost.total_tokens,
        cache_creation_tokens=cost.cache_creation_tokens,
        cache_read_tokens=cost.cache_read_tokens,
        tool_calls=cost.tool_calls,
        turns=cost.turns,
        duration_ms=cost.duration_ms,
        cost_by_model={k: str(v) for k, v in cost.cost_by_model.items()},
        cost_by_tool={k: str(v) for k, v in cost.cost_by_tool.items()},
        tokens_by_tool=cost.tokens_by_tool,
        cost_by_tool_tokens={k: str(v) for k, v in cost.cost_by_tool_tokens.items()},
        is_finalized=cost.is_finalized,
        started_at=cost.started_at,
        completed_at=cost.completed_at,
    )


def _domain_execution_cost_to_api(cost: ExecutionCost) -> ExecutionCostResponse:
    """Convert domain ExecutionCost to API ExecutionCostResponse."""
    return ExecutionCostResponse(
        execution_id=cost.execution_id,
        workflow_id=cost.workflow_id,
        session_count=cost.session_count,
        session_ids=cost.session_ids,
        total_cost_usd=cost.total_cost_usd,
        token_cost_usd=cost.token_cost_usd,
        compute_cost_usd=cost.compute_cost_usd,
        input_tokens=cost.input_tokens,
        output_tokens=cost.output_tokens,
        total_tokens=cost.total_tokens,
        cache_creation_tokens=cost.cache_creation_tokens,
        cache_read_tokens=cost.cache_read_tokens,
        tool_calls=cost.tool_calls,
        turns=cost.turns,
        duration_ms=cost.duration_ms,
        cost_by_phase={k: str(v) for k, v in cost.cost_by_phase.items()},
        cost_by_model={k: str(v) for k, v in cost.cost_by_model.items()},
        cost_by_tool={k: str(v) for k, v in cost.cost_by_tool.items()},
        is_complete=cost.is_complete,
        started_at=cost.started_at,
        completed_at=cost.completed_at,
    )


@router.get("/sessions", response_model=list[SessionCostResponse])
async def list_session_costs(
    execution_id: str | None = Query(None, description="Filter by execution ID"),
    limit: int = Query(50, ge=1, le=200, description="Max items to return"),
) -> list[SessionCostResponse]:
    """List session costs with optional filtering."""
    manager = get_projection_manager()
    projection = manager.session_cost

    if execution_id:
        sessions = await projection.get_sessions_for_execution(execution_id)
    else:
        sessions = await projection.get_all()

    # Apply limit
    sessions = sessions[:limit]

    return [_domain_session_cost_to_api(s) for s in sessions]


@router.get("/sessions/{session_id}", response_model=SessionCostResponse)
async def get_session_cost(
    session_id: str,
    include_breakdown: bool = Query(True, description="Include model/tool breakdowns"),
) -> SessionCostResponse:
    """Get cost for a specific session."""
    manager = get_projection_manager()
    projection = manager.session_cost

    session_cost = await projection.get_session_cost(session_id)

    if session_cost is None:
        raise HTTPException(
            status_code=404,
            detail=f"Session cost not found for session {session_id}",
        )

    # Convert to API response, optionally excluding breakdown
    response = _domain_session_cost_to_api(session_cost)
    if not include_breakdown:
        response.cost_by_model = {}
        response.cost_by_tool = {}

    return response


@router.get("/executions", response_model=list[ExecutionCostResponse])
async def list_execution_costs(
    limit: int = Query(50, ge=1, le=200, description="Max items to return"),
) -> list[ExecutionCostResponse]:
    """List execution costs."""
    manager = get_projection_manager()
    projection = manager.execution_cost

    executions = await projection.get_all()

    # Apply limit
    executions = executions[:limit]

    return [_domain_execution_cost_to_api(e) for e in executions]


@router.get("/executions/{execution_id}", response_model=ExecutionCostResponse)
async def get_execution_cost(
    execution_id: str,
    include_breakdown: bool = Query(True, description="Include phase/model/tool breakdowns"),
    include_session_ids: bool = Query(False, description="Include list of session IDs"),
) -> ExecutionCostResponse:
    """Get aggregated cost for a workflow execution."""
    manager = get_projection_manager()
    projection = manager.execution_cost

    execution_cost = await projection.get_execution_cost(execution_id)

    if execution_cost is None:
        raise HTTPException(
            status_code=404,
            detail=f"Execution cost not found for execution {execution_id}",
        )

    # Convert to API response, optionally excluding breakdown and session IDs
    response = _domain_execution_cost_to_api(execution_cost)
    if not include_breakdown:
        response.cost_by_phase = {}
        response.cost_by_model = {}
        response.cost_by_tool = {}

    if not include_session_ids:
        response.session_ids = []

    return response


@router.get("/summary", response_model=CostSummaryResponse)
async def get_cost_summary() -> CostSummaryResponse:
    """Get summary of all costs across sessions and executions."""
    manager = get_projection_manager()

    # Get all session costs
    session_costs = await manager.session_cost.get_all()

    # Get all execution costs
    execution_costs = await manager.execution_cost.get_all()

    # Aggregate totals from sessions (the atomic unit)
    total_cost = Decimal("0")
    total_tokens = 0
    total_tool_calls = 0
    model_costs: dict[str, Decimal] = {}

    for session in session_costs:
        total_cost += session.total_cost_usd
        total_tokens += session.total_tokens
        total_tool_calls += session.tool_calls

        for model, cost in session.cost_by_model.items():
            model_costs[model] = model_costs.get(model, Decimal("0")) + cost

    # Build top models
    sorted_models = sorted(model_costs.items(), key=lambda x: x[1], reverse=True)
    top_models = [{"model": model, "cost_usd": str(cost)} for model, cost in sorted_models[:5]]

    # Build top sessions by cost
    sorted_sessions = sorted(session_costs, key=lambda s: s.total_cost_usd, reverse=True)
    top_sessions = [
        {
            "session_id": s.session_id,
            "cost_usd": str(s.total_cost_usd),
            "tokens": s.total_tokens,
        }
        for s in sorted_sessions[:5]
    ]

    return CostSummaryResponse(
        total_cost_usd=total_cost,
        total_sessions=len(session_costs),
        total_executions=len(execution_costs),
        total_tokens=total_tokens,
        total_tool_calls=total_tool_calls,
        top_models=top_models,
        top_sessions=top_sessions,
    )
