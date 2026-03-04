"""Execution operations — execute, list, get, control, and query state.

Extracted from ``v1.workflows`` to separate template CRUD from execution lifecycle.
"""

from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Literal

from syn_api._wiring import (
    ensure_connected,
    get_controller,
    get_execution_engine,
    get_projection_mgr,
)
from syn_api.types import (
    ControlResult,
    Err,
    ExecutionDetail,
    ExecutionDetailFull,
    ExecutionError,
    ExecutionSummary,
    Ok,
    PhaseExecution,
    Result,
    ToolOperation,
    WorkflowError,
)

if TYPE_CHECKING:
    from syn_api.auth import AuthContext

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Execution CRUD (moved from workflows.py)
# ---------------------------------------------------------------------------


async def execute(
    workflow_id: str,
    inputs: dict[str, str] | None = None,
    execution_id: str | None = None,
    use_container: bool = True,  # noqa: ARG001
    tenant_id: str | None = None,  # noqa: ARG001
    auth: AuthContext | None = None,  # noqa: ARG001
) -> Result[ExecutionSummary, WorkflowError]:
    """Execute a workflow.

    Args:
        workflow_id: ID of the workflow template to execute.
        inputs: Input variables for the workflow.
        execution_id: Optional execution ID (auto-generated if omitted).
        use_container: Whether to use container isolation (default True).
        tenant_id: Optional tenant ID for multi-tenant deployments.
        auth: Optional authentication context.

    Returns:
        Ok(ExecutionSummary) on success, Err(WorkflowError) on failure.
    """
    from syn_domain.contexts.orchestration.slices.execute_workflow.WorkflowExecutionEngine import (
        WorkflowNotFoundError,
    )

    await ensure_connected()

    manager = get_projection_mgr()
    detail = await manager.workflow_detail.get_by_id(workflow_id)
    workflow_name = detail.name if detail else ""

    engine = await get_execution_engine()

    try:
        result = await engine.execute(
            workflow_id=workflow_id,
            inputs=inputs or {},
            execution_id=execution_id,
        )
    except WorkflowNotFoundError:
        return Err(WorkflowError.NOT_FOUND, message=f"Workflow {workflow_id} not found")
    except Exception as e:
        return Err(WorkflowError.EXECUTION_FAILED, message=str(e))

    return Ok(
        ExecutionSummary(
            workflow_execution_id=result.execution_id,
            workflow_id=workflow_id,
            workflow_name=workflow_name,
            status=result.status.value,
            completed_phases=result.metrics.completed_phases,
            total_phases=result.metrics.total_phases,
            total_tokens=result.metrics.total_tokens,
            total_cost_usd=result.metrics.total_cost_usd,
            error_message=result.error_message,
        )
    )


async def get(
    execution_id: str,
    auth: AuthContext | None = None,  # noqa: ARG001
) -> Result[ExecutionDetail, ExecutionError]:
    """Get detailed information about a workflow execution.

    Args:
        execution_id: The execution ID.
        auth: Optional authentication context.

    Returns:
        Ok(ExecutionDetail) on success, Err(ExecutionError.NOT_FOUND) if missing.
    """
    await ensure_connected()
    manager = get_projection_mgr()
    detail = await manager.workflow_execution_detail.get_by_id(execution_id)
    if detail is None:
        return Err(ExecutionError.NOT_FOUND, message=f"Execution {execution_id} not found")
    return Ok(
        ExecutionDetail(
            workflow_execution_id=detail.workflow_execution_id,
            workflow_id=detail.workflow_id,
            workflow_name=detail.workflow_name,
            status=detail.status,
            started_at=detail.started_at,
            completed_at=detail.completed_at,
            total_input_tokens=detail.total_input_tokens,
            total_output_tokens=detail.total_output_tokens,
            total_cost_usd=detail.total_cost_usd,
            total_duration_seconds=detail.total_duration_seconds,
            artifact_ids=list(detail.artifact_ids),
            error_message=detail.error_message,
        )
    )


async def list_(
    workflow_id: str | None = None,
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
    auth: AuthContext | None = None,  # noqa: ARG001
) -> Result[list[ExecutionSummary], ExecutionError]:
    """List workflow executions.

    Args:
        workflow_id: Optional filter by workflow ID.
        status: Optional filter by execution status.
        limit: Maximum results to return.
        offset: Pagination offset.
        auth: Optional authentication context.

    Returns:
        Ok(list[ExecutionSummary]) on success, Err(ExecutionError) on failure.
    """
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

    # Batch-query tool call counts from agent_events (one query for all executions)
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
                        """
                        SELECT execution_id, COUNT(*) AS cnt
                        FROM agent_events
                        WHERE execution_id = ANY($1)
                          AND event_type = 'tool_execution_completed'
                        GROUP BY execution_id
                        """,
                        exec_ids,
                    )
                tool_counts = {row["execution_id"]: row["cnt"] for row in rows}
        except Exception:
            logger.debug("Could not query tool counts from agent_events", exc_info=True)

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


# ---------------------------------------------------------------------------
# Execution detail (new)
# ---------------------------------------------------------------------------


async def get_detail(
    execution_id: str,
    auth: AuthContext | None = None,  # noqa: ARG001
) -> Result[ExecutionDetailFull, ExecutionError]:
    """Get rich execution detail with phases and tool operations.

    Args:
        execution_id: The execution ID.
        auth: Optional authentication context.

    Returns:
        Ok(ExecutionDetailFull) on success, Err(ExecutionError) on failure.
    """
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
                    logger.exception("Failed to load tool operations for session %s", session_id)

            _p_started = p.started_at if hasattr(p, "started_at") else None
            _p_completed = p.completed_at if hasattr(p, "completed_at") else None
            phases.append(
                PhaseExecution(
                    phase_id=p.workflow_phase_id,
                    name=p.name,
                    status=p.status,
                    session_id=session_id,
                    artifact_id=p.artifact_id if hasattr(p, "artifact_id") else None,
                    input_tokens=p.input_tokens,
                    output_tokens=p.output_tokens,
                    cost_usd=Decimal(str(p.cost_usd)),
                    duration_seconds=p.duration_seconds if hasattr(p, "duration_seconds") else None,
                    started_at=datetime.fromisoformat(_p_started)
                    if isinstance(_p_started, str)
                    else _p_started,
                    completed_at=datetime.fromisoformat(_p_completed)
                    if isinstance(_p_completed, str)
                    else _p_completed,
                    operations=ops,
                )
            )

    return Ok(
        ExecutionDetailFull(
            workflow_execution_id=detail.workflow_execution_id,
            workflow_id=detail.workflow_id,
            workflow_name=detail.workflow_name,
            status=detail.status,
            phases=phases,
            total_tokens=detail.total_input_tokens + detail.total_output_tokens,
            total_cost_usd=detail.total_cost_usd,
            started_at=detail.started_at,
            completed_at=detail.completed_at,
            error_message=detail.error_message,
        )
    )


async def list_active(
    limit: int = 50,
    auth: AuthContext | None = None,  # noqa: ARG001
) -> Result[list[ExecutionSummary], ExecutionError]:
    """List currently running or paused executions.

    Args:
        limit: Maximum results to return.
        auth: Optional authentication context.
    """
    await ensure_connected()
    manager = get_projection_mgr()
    projection = manager.workflow_execution_list

    all_execs = await projection.get_all(limit=limit, status_filter=None)
    active = [
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
    return Ok(active)


# ---------------------------------------------------------------------------
# Control operations
# ---------------------------------------------------------------------------


async def pause(
    execution_id: str,
    reason: str | None = None,
    auth: AuthContext | None = None,  # noqa: ARG001
) -> Result[ControlResult, ExecutionError]:
    """Pause a running execution at the next yield point.

    Args:
        execution_id: The execution to pause.
        reason: Optional reason for pausing.
        auth: Optional authentication context.
    """
    from syn_adapters.control.commands import PauseExecution

    try:
        controller = get_controller()
        domain_result = await controller.handle_command(
            PauseExecution(execution_id=execution_id, reason=reason)
        )
        return Ok(
            ControlResult(
                success=domain_result.success,
                execution_id=domain_result.execution_id,
                new_state=domain_result.new_state,
                message=domain_result.message,
                error=domain_result.error,
            )
        )
    except Exception as e:
        return Err(ExecutionError.SIGNAL_FAILED, message=str(e))


async def resume(
    execution_id: str,
    auth: AuthContext | None = None,  # noqa: ARG001
) -> Result[ControlResult, ExecutionError]:
    """Resume a paused execution.

    Args:
        execution_id: The execution to resume.
        auth: Optional authentication context.
    """
    from syn_adapters.control.commands import ResumeExecution

    try:
        controller = get_controller()
        domain_result = await controller.handle_command(ResumeExecution(execution_id=execution_id))
        return Ok(
            ControlResult(
                success=domain_result.success,
                execution_id=domain_result.execution_id,
                new_state=domain_result.new_state,
                message=domain_result.message,
                error=domain_result.error,
            )
        )
    except Exception as e:
        return Err(ExecutionError.SIGNAL_FAILED, message=str(e))


async def cancel(
    execution_id: str,
    reason: str | None = None,
    auth: AuthContext | None = None,  # noqa: ARG001
) -> Result[ControlResult, ExecutionError]:
    """Cancel a running or paused execution.

    Args:
        execution_id: The execution to cancel.
        reason: Optional reason for cancellation.
        auth: Optional authentication context.
    """
    from syn_adapters.control.commands import CancelExecution

    try:
        controller = get_controller()
        domain_result = await controller.handle_command(
            CancelExecution(execution_id=execution_id, reason=reason)
        )
        return Ok(
            ControlResult(
                success=domain_result.success,
                execution_id=domain_result.execution_id,
                new_state=domain_result.new_state,
                message=domain_result.message,
                error=domain_result.error,
            )
        )
    except Exception as e:
        return Err(ExecutionError.SIGNAL_FAILED, message=str(e))


async def inject(
    execution_id: str,
    message: str,
    role: Literal["user", "system"] = "user",
    auth: AuthContext | None = None,  # noqa: ARG001
) -> Result[ControlResult, ExecutionError]:
    """Inject a message into an execution's agent context.

    Args:
        execution_id: The execution to inject into.
        message: The message content.
        role: Message role ("user" or "system").
        auth: Optional authentication context.
    """
    from syn_adapters.control.commands import InjectContext

    try:
        controller = get_controller()
        domain_result = await controller.handle_command(
            InjectContext(execution_id=execution_id, message=message, role=role)
        )
        return Ok(
            ControlResult(
                success=domain_result.success,
                execution_id=domain_result.execution_id,
                new_state=domain_result.new_state,
                message=domain_result.message,
                error=domain_result.error,
            )
        )
    except Exception as e:
        return Err(ExecutionError.SIGNAL_FAILED, message=str(e))


async def get_state(
    execution_id: str,
    auth: AuthContext | None = None,  # noqa: ARG001
) -> Result[dict, ExecutionError]:
    """Get the current control state of an execution.

    Args:
        execution_id: The execution to query.
        auth: Optional authentication context.

    Returns:
        Ok(dict) with state info, Err(ExecutionError) on failure.
    """
    try:
        controller = get_controller()
        state = await controller.get_state(execution_id)
        if state is None:
            return Err(
                ExecutionError.NOT_FOUND,
                message=f"No state found for execution {execution_id}",
            )
        return Ok(
            {
                "execution_id": execution_id,
                "state": state.value if hasattr(state, "value") else str(state),
            }
        )
    except Exception as e:
        return Err(ExecutionError.NOT_FOUND, message=str(e))
