"""Metrics operations — dashboard metrics and cost tracking.

Merges the dashboard's metrics and costs endpoints into a single module.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from aef_api._wiring import ensure_connected, get_projection_mgr
from aef_api.types import (
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
    from aef_api.auth import AuthContext


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
                total_workflows=getattr(data, "total_workflows", 0),
                completed_workflows=getattr(data, "completed_workflows", 0),
                failed_workflows=getattr(data, "failed_workflows", 0),
                total_sessions=getattr(data, "total_sessions", 0),
                total_input_tokens=getattr(data, "total_input_tokens", 0),
                total_output_tokens=getattr(data, "total_output_tokens", 0),
                total_tokens=getattr(data, "total_tokens", 0),
                total_cost_usd=Decimal(str(getattr(data, "total_cost_usd", 0))),
                total_artifacts=getattr(data, "total_artifacts", 0),
                total_artifact_bytes=getattr(data, "total_artifact_bytes", 0),
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
                    session_id=getattr(c, "session_id", ""),
                    execution_id=getattr(c, "execution_id", None),
                    workflow_id=getattr(c, "workflow_id", None),
                    phase_id=getattr(c, "phase_id", None),
                    total_cost_usd=Decimal(str(getattr(c, "total_cost_usd", 0))),
                    token_cost_usd=Decimal(str(getattr(c, "token_cost_usd", 0))),
                    input_tokens=getattr(c, "input_tokens", 0),
                    output_tokens=getattr(c, "output_tokens", 0),
                    total_tokens=getattr(c, "total_tokens", 0),
                    cache_creation_tokens=getattr(c, "cache_creation_tokens", 0),
                    cache_read_tokens=getattr(c, "cache_read_tokens", 0),
                    tool_calls=getattr(c, "tool_calls", 0),
                    turns=getattr(c, "turns", 0),
                    duration_ms=getattr(c, "duration_ms", 0),
                    cost_by_model=getattr(c, "cost_by_model", {}),
                    cost_by_tool=getattr(c, "cost_by_tool", {}),
                    is_finalized=getattr(c, "is_finalized", False),
                    started_at=getattr(c, "started_at", None),
                    completed_at=getattr(c, "completed_at", None),
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
                session_id=getattr(c, "session_id", session_id),
                execution_id=getattr(c, "execution_id", None),
                workflow_id=getattr(c, "workflow_id", None),
                phase_id=getattr(c, "phase_id", None),
                total_cost_usd=Decimal(str(getattr(c, "total_cost_usd", 0))),
                token_cost_usd=Decimal(str(getattr(c, "token_cost_usd", 0))),
                input_tokens=getattr(c, "input_tokens", 0),
                output_tokens=getattr(c, "output_tokens", 0),
                total_tokens=getattr(c, "total_tokens", 0),
                cache_creation_tokens=getattr(c, "cache_creation_tokens", 0),
                cache_read_tokens=getattr(c, "cache_read_tokens", 0),
                tool_calls=getattr(c, "tool_calls", 0),
                turns=getattr(c, "turns", 0),
                duration_ms=getattr(c, "duration_ms", 0),
                cost_by_model=getattr(c, "cost_by_model", {}),
                cost_by_tool=getattr(c, "cost_by_tool", {}),
                is_finalized=getattr(c, "is_finalized", False),
                started_at=getattr(c, "started_at", None),
                completed_at=getattr(c, "completed_at", None),
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
                    execution_id=getattr(c, "execution_id", ""),
                    workflow_id=getattr(c, "workflow_id", None),
                    session_count=getattr(c, "session_count", 0),
                    session_ids=getattr(c, "session_ids", []),
                    total_cost_usd=Decimal(str(getattr(c, "total_cost_usd", 0))),
                    input_tokens=getattr(c, "input_tokens", 0),
                    output_tokens=getattr(c, "output_tokens", 0),
                    total_tokens=getattr(c, "total_tokens", 0),
                    cost_by_phase=getattr(c, "cost_by_phase", {}),
                    cost_by_model=getattr(c, "cost_by_model", {}),
                    cost_by_tool=getattr(c, "cost_by_tool", {}),
                    is_complete=getattr(c, "is_complete", False),
                    started_at=getattr(c, "started_at", None),
                    completed_at=getattr(c, "completed_at", None),
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
                execution_id=getattr(c, "execution_id", execution_id),
                workflow_id=getattr(c, "workflow_id", None),
                session_count=getattr(c, "session_count", 0),
                session_ids=getattr(c, "session_ids", []),
                total_cost_usd=Decimal(str(getattr(c, "total_cost_usd", 0))),
                input_tokens=getattr(c, "input_tokens", 0),
                output_tokens=getattr(c, "output_tokens", 0),
                total_tokens=getattr(c, "total_tokens", 0),
                cost_by_phase=getattr(c, "cost_by_phase", {}),
                cost_by_model=getattr(c, "cost_by_model", {}),
                cost_by_tool=getattr(c, "cost_by_tool", {}),
                is_complete=getattr(c, "is_complete", False),
                started_at=getattr(c, "started_at", None),
                completed_at=getattr(c, "completed_at", None),
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

        total_cost = Decimal(str(sum(getattr(c, "total_cost_usd", 0) for c in (all_costs or []))))
        total_tokens = sum(getattr(c, "total_tokens", 0) for c in (all_costs or []))
        total_sessions = sum(getattr(c, "session_count", 0) for c in (all_costs or []))

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
