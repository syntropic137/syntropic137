"""Metrics operations — dashboard metrics and cost tracking.

Merges the dashboard's metrics and costs endpoints into a single module.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from syn_api._wiring import ensure_connected, get_projection_mgr
from syn_api.types import (
    CostSummary,
    DashboardMetrics,
    Err,
    ExecutionCostData,
    MetricsError,
    Ok,
    Result,
    SessionCostData,
)

if TYPE_CHECKING:
    from syn_api.auth import AuthContext


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


async def list_session_costs(
    execution_id: str | None = None,
    limit: int = 100,  # noqa: ARG001
    auth: AuthContext | None = None,  # noqa: ARG001
) -> Result[list[SessionCostData], MetricsError]:
    """List cost data for sessions.

    Args:
        execution_id: Optional filter by execution ID.
        limit: Maximum results to return.
        auth: Optional authentication context.
    """
    await ensure_connected()
    try:
        manager = get_projection_mgr()
        projection = manager.session_cost

        if execution_id:
            costs = await projection.get_sessions_for_execution(execution_id)
        else:
            costs = await projection.get_all()

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
                for c in (costs or [])
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

    Args:
        session_id: The session ID.
        include_breakdown: Whether to include model/tool breakdowns.
        auth: Optional authentication context.
    """
    await ensure_connected()
    try:
        manager = get_projection_mgr()
        projection = manager.session_cost
        c = await projection.get_session_cost(session_id)

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
    limit: int = 100,  # noqa: ARG001
    auth: AuthContext | None = None,  # noqa: ARG001
) -> Result[list[ExecutionCostData], MetricsError]:
    """List cost data for executions.

    Args:
        limit: Maximum results to return.
        auth: Optional authentication context.
    """
    await ensure_connected()
    try:
        manager = get_projection_mgr()
        projection = manager.execution_cost
        costs = await projection.get_all()

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
                for c in (costs or [])
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

    Args:
        execution_id: The execution ID.
        include_breakdown: Whether to include phase/model/tool breakdowns.
        auth: Optional authentication context.
    """
    await ensure_connected()
    try:
        manager = get_projection_mgr()
        projection = manager.execution_cost
        c = await projection.get_execution_cost(execution_id)

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

    Args:
        auth: Optional authentication context.
    """
    await ensure_connected()
    try:
        manager = get_projection_mgr()

        # Aggregate from execution_cost projection
        exec_projection = manager.execution_cost
        all_costs = await exec_projection.get_all()

        total_cost = Decimal(str(sum(c.total_cost_usd for c in (all_costs or []))))
        total_tokens = sum(c.total_tokens for c in (all_costs or []))
        total_sessions = sum(c.session_count for c in (all_costs or []))

        return Ok(
            CostSummary(
                total_cost_usd=total_cost,
                total_sessions=total_sessions,
                total_executions=len(all_costs or []),
                total_tokens=total_tokens,
                total_tool_calls=0,
                top_models=[],
                top_sessions=[],
            )
        )
    except Exception as e:
        return Err(MetricsError.QUERY_FAILED, message=str(e))
