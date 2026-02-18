"""Cost tracking API endpoints — thin wrapper over syn_api."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from fastapi import APIRouter, HTTPException, Query

import syn_api.v1.metrics as met
from syn_api.types import Err
from syn_dashboard.models.schemas import (
    CostSummaryResponse,
    ExecutionCostResponse,
    SessionCostResponse,
)

router = APIRouter(prefix="/costs", tags=["costs"])


def _session_cost_to_api(c: Any) -> SessionCostResponse:
    """Convert syn_api SessionCostData to dashboard SessionCostResponse."""
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
        started_at=c.started_at,
        completed_at=c.completed_at,
    )


def _execution_cost_to_api(c: Any) -> ExecutionCostResponse:
    """Convert syn_api ExecutionCostData to dashboard ExecutionCostResponse."""
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
        started_at=c.started_at,
        completed_at=c.completed_at,
    )


@router.get("/sessions", response_model=list[SessionCostResponse])
async def list_session_costs(
    execution_id: str | None = Query(None, description="Filter by execution ID"),
    limit: int = Query(50, ge=1, le=200, description="Max items to return"),
) -> list[SessionCostResponse]:
    """List session costs with optional filtering."""
    result = await met.list_session_costs(execution_id=execution_id, limit=limit)

    if isinstance(result, Err):
        raise HTTPException(status_code=500, detail=result.message)

    return [_session_cost_to_api(s) for s in result.value]


@router.get("/sessions/{session_id}", response_model=SessionCostResponse)
async def get_session_cost(
    session_id: str,
    include_breakdown: bool = Query(True, description="Include model/tool breakdowns"),
) -> SessionCostResponse:
    """Get cost for a specific session."""
    result = await met.get_session_cost(session_id, include_breakdown=include_breakdown)

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
async def list_execution_costs(
    limit: int = Query(50, ge=1, le=200, description="Max items to return"),
) -> list[ExecutionCostResponse]:
    """List execution costs."""
    result = await met.list_execution_costs(limit=limit)

    if isinstance(result, Err):
        raise HTTPException(status_code=500, detail=result.message)

    return [_execution_cost_to_api(e) for e in result.value]


@router.get("/executions/{execution_id}", response_model=ExecutionCostResponse)
async def get_execution_cost(
    execution_id: str,
    include_breakdown: bool = Query(True, description="Include phase/model/tool breakdowns"),
    include_session_ids: bool = Query(False, description="Include list of session IDs"),
) -> ExecutionCostResponse:
    """Get aggregated cost for a workflow execution."""
    result = await met.get_execution_cost(execution_id, include_breakdown=include_breakdown)

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
async def get_cost_summary() -> CostSummaryResponse:
    """Get summary of all costs across sessions and executions."""
    result = await met.get_cost_summary()

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
