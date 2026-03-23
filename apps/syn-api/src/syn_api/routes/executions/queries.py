"""Execution query endpoints and service functions."""

from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from syn_api._wiring import ensure_connected, get_projection_mgr
from syn_api.types import (
    Err, ExecutionDetail, ExecutionDetailFull, ExecutionError,
    ExecutionSummary, Ok, PhaseExecution, Result, ToolOperation,
)

if TYPE_CHECKING:
    from syn_api.auth import AuthContext

logger = logging.getLogger(__name__)
router = APIRouter(tags=["executions"])

# -- Response Models ----------------------------------------------------------

class PhaseOperationInfo(BaseModel):
    operation_id: str
    operation_type: str
    timestamp: str | None = None
    tool_name: str | None = None
    tool_use_id: str | None = None
    success: bool = True

class PhaseExecutionInfo(BaseModel):
    phase_id: str
    name: str
    status: str
    session_id: str | None = None
    artifact_id: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    duration_seconds: float = 0.0
    cost_usd: Decimal = Decimal("0")
    started_at: str | None = None
    completed_at: str | None = None
    error_message: str | None = None
    operations: list[PhaseOperationInfo] = []

class ExecutionDetailResponse(BaseModel):
    workflow_execution_id: str
    workflow_id: str
    workflow_name: str
    status: str
    started_at: str | None = None
    completed_at: str | None = None
    phases: list[PhaseExecutionInfo] = Field(default_factory=list)
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_tokens: int = 0
    total_cost_usd: Decimal = Decimal("0")
    total_duration_seconds: float = 0.0
    artifact_ids: list[str] = Field(default_factory=list)
    error_message: str | None = None

class ExecutionSummaryResponse(BaseModel):
    workflow_execution_id: str
    workflow_id: str
    workflow_name: str
    status: str
    started_at: str | None = None
    completed_at: str | None = None
    completed_phases: int = 0
    total_phases: int = 0
    total_tokens: int = 0
    total_cost_usd: Decimal = Decimal("0")
    tool_call_count: int = 0

class ExecutionListResponse(BaseModel):
    executions: list[ExecutionSummaryResponse]
    total: int
    page: int = 1
    page_size: int = 50

# -- Helpers ------------------------------------------------------------------

def _to_str(val: object | None) -> str | None:
    return str(val) if val is not None else None

# -- Service functions --------------------------------------------------------

async def list_(
    workflow_id: str | None = None, status: str | None = None,
    limit: int = 100, offset: int = 0,
    auth: AuthContext | None = None,  # noqa: ARG001
) -> Result[list[ExecutionSummary], ExecutionError]:
    await ensure_connected()
    manager = get_projection_mgr()
    projection = manager.workflow_execution_list
    if workflow_id:
        domain_summaries = await projection.get_by_workflow_id(workflow_id)
    else:
        domain_summaries = await projection.get_all(
            limit=limit, offset=offset, status_filter=status,
        )
    tool_counts: dict[str, int] = {}
    if domain_summaries:
        try:
            from syn_api._wiring import get_event_store_instance
            event_store = get_event_store_instance()
            pool = event_store.pool
            if pool is not None:
                exec_ids = [s.workflow_execution_id for s in domain_summaries]
                async with pool.acquire() as conn:
                    rows = await conn.fetch(
                        "SELECT execution_id, COUNT(*) AS cnt "
                        "FROM agent_events "
                        "WHERE execution_id = ANY($1) "
                        "  AND event_type = 'tool_execution_completed' "
                        "GROUP BY execution_id",
                        exec_ids,
                    )
                tool_counts = {row["execution_id"]: row["cnt"] for row in rows}
        except Exception:
            logger.debug("Could not query tool counts from agent_events", exc_info=True)
    return Ok([
        ExecutionSummary(
            workflow_execution_id=s.workflow_execution_id,
            workflow_id=s.workflow_id, workflow_name=s.workflow_name,
            status=s.status, started_at=s.started_at, completed_at=s.completed_at,
            completed_phases=s.completed_phases, total_phases=s.total_phases,
            total_tokens=s.total_tokens, total_cost_usd=s.total_cost_usd,
            tool_call_count=tool_counts.get(s.workflow_execution_id, 0),
            error_message=s.error_message,
        ) for s in domain_summaries
    ])


async def get(
    execution_id: str, auth: AuthContext | None = None,  # noqa: ARG001
) -> Result[ExecutionDetail, ExecutionError]:
    await ensure_connected()
    detail = await get_projection_mgr().workflow_execution_detail.get_by_id(execution_id)
    if detail is None:
        return Err(ExecutionError.NOT_FOUND, message=f"Execution {execution_id} not found")
    return Ok(ExecutionDetail(
        workflow_execution_id=detail.workflow_execution_id,
        workflow_id=detail.workflow_id, workflow_name=detail.workflow_name,
        status=detail.status, started_at=detail.started_at,
        completed_at=detail.completed_at,
        total_input_tokens=detail.total_input_tokens,
        total_output_tokens=detail.total_output_tokens,
        total_cost_usd=detail.total_cost_usd,
        total_duration_seconds=detail.total_duration_seconds,
        artifact_ids=list(detail.artifact_ids), error_message=detail.error_message,
    ))


async def get_detail(
    execution_id: str, auth: AuthContext | None = None,  # noqa: ARG001
) -> Result[ExecutionDetailFull, ExecutionError]:
    await ensure_connected()
    manager = get_projection_mgr()
    detail = await manager.workflow_execution_detail.get_by_id(execution_id)
    if detail is None:
        return Err(ExecutionError.NOT_FOUND, message=f"Execution {execution_id} not found")
    phases: list[PhaseExecution] = []
    if hasattr(detail, "phases") and detail.phases:
        for p in detail.phases:
            ops: list[ToolOperation] = []
            session_id = p.session_id if hasattr(p, "session_id") else None
            if session_id:
                try:
                    tool_data = await manager.session_tools.get(session_id)
                    ops = [
                        ToolOperation(
                            observation_id=op.observation_id, operation_type=op.operation_type,
                            timestamp=op.timestamp, duration_ms=op.duration_ms,
                            success=op.success, tool_name=op.tool_name, tool_use_id=op.tool_use_id,
                        ) for op in (tool_data or [])
                    ]
                except Exception:
                    logger.exception("Failed to load tool ops for session %s", session_id)
            _st = p.started_at if hasattr(p, "started_at") else None
            _co = p.completed_at if hasattr(p, "completed_at") else None
            phases.append(PhaseExecution(
                phase_id=p.workflow_phase_id, name=p.name, status=p.status,
                session_id=session_id,
                artifact_id=p.artifact_id if hasattr(p, "artifact_id") else None,
                input_tokens=p.input_tokens, output_tokens=p.output_tokens,
                cost_usd=Decimal(str(p.cost_usd)),
                duration_seconds=p.duration_seconds if hasattr(p, "duration_seconds") else None,
                started_at=datetime.fromisoformat(_st) if isinstance(_st, str) else _st,
                completed_at=datetime.fromisoformat(_co) if isinstance(_co, str) else _co,
                operations=ops,
            ))
    return Ok(ExecutionDetailFull(
        workflow_execution_id=detail.workflow_execution_id,
        workflow_id=detail.workflow_id, workflow_name=detail.workflow_name,
        status=detail.status, phases=phases,
        total_tokens=detail.total_input_tokens + detail.total_output_tokens,
        total_cost_usd=detail.total_cost_usd,
        started_at=detail.started_at, completed_at=detail.completed_at,
        error_message=detail.error_message,
    ))


async def list_active(
    limit: int = 50, auth: AuthContext | None = None,  # noqa: ARG001
) -> Result[list[ExecutionSummary], ExecutionError]:
    """List currently running or paused executions."""
    await ensure_connected()
    all_execs = await get_projection_mgr().workflow_execution_list.get_all(
        limit=limit, status_filter=None,
    )
    return Ok([
        ExecutionSummary(
            workflow_execution_id=s.workflow_execution_id,
            workflow_id=s.workflow_id, workflow_name=s.workflow_name,
            status=s.status, started_at=s.started_at, completed_at=s.completed_at,
            completed_phases=s.completed_phases, total_phases=s.total_phases,
            total_tokens=s.total_tokens, total_cost_usd=s.total_cost_usd,
            error_message=s.error_message,
        ) for s in all_execs if s.status in ("running", "paused", "pending")
    ])

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
                workflow_id=e.workflow_id, workflow_name=e.workflow_name,
                status=e.status, started_at=_to_str(e.started_at),
                completed_at=_to_str(e.completed_at),
                completed_phases=e.completed_phases, total_phases=e.total_phases,
                total_tokens=e.total_tokens,
                total_cost_usd=Decimal(str(e.total_cost_usd)),
                tool_call_count=e.tool_call_count,
            ) for e in result.value
        ],
        total=len(result.value), page=page, page_size=page_size,
    )

@router.get("/executions/{execution_id}", response_model=ExecutionDetailResponse)
async def get_execution_endpoint(execution_id: str) -> ExecutionDetailResponse:
    """Get detailed information about a workflow execution run."""
    result = await get_detail(execution_id)
    if isinstance(result, Err):
        raise HTTPException(status_code=404, detail=f"Execution {execution_id} not found")
    detail = result.value
    phases = []
    for p in detail.phases or []:
        operations = [
            PhaseOperationInfo(
                operation_id=op.observation_id, operation_type=op.operation_type,
                timestamp=str(op.timestamp) if op.timestamp else None,
                tool_name=op.tool_name, tool_use_id=op.tool_use_id,
                success=op.success if op.success is not None else True,
            ) for op in (p.operations or [])
        ]
        phases.append(PhaseExecutionInfo(
            phase_id=p.phase_id, name=p.name, status=p.status,
            session_id=p.session_id, artifact_id=p.artifact_id,
            input_tokens=p.input_tokens, output_tokens=p.output_tokens,
            total_tokens=p.input_tokens + p.output_tokens,
            duration_seconds=p.duration_seconds or 0.0, cost_usd=Decimal(str(p.cost_usd)),
            started_at=str(p.started_at) if p.started_at else None,
            completed_at=str(p.completed_at) if p.completed_at else None,
            operations=operations,
        ))
    total_input = sum(p.input_tokens for p in detail.phases or [])
    total_output = sum(p.output_tokens for p in detail.phases or [])
    artifact_ids = [p.artifact_id for p in phases if p.artifact_id]
    return ExecutionDetailResponse(
        workflow_execution_id=detail.workflow_execution_id,
        workflow_id=detail.workflow_id, workflow_name=detail.workflow_name,
        status=detail.status,
        started_at=str(detail.started_at) if detail.started_at else None,
        completed_at=str(detail.completed_at) if detail.completed_at else None,
        phases=phases, total_input_tokens=total_input,
        total_output_tokens=total_output, total_tokens=detail.total_tokens,
        total_cost_usd=Decimal(str(detail.total_cost_usd)),
        artifact_ids=artifact_ids, error_message=detail.error_message,
    )
