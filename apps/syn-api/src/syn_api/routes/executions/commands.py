"""Execution command endpoints and service functions.

Execute workflow (with background task) and execution status queries scoped
to a specific workflow.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from syn_api._wiring import (
    ensure_connected,
    get_execution_processor,
    get_projection_mgr,
)
from syn_api.types import (
    Err,
    ExecutionSummary,
    Ok,
    Result,
    WorkflowError,
)

if TYPE_CHECKING:
    from syn_api.auth import AuthContext

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/workflows", tags=["execution"])


# -- Request/Response Models --------------------------------------------------


class ExecuteWorkflowRequest(BaseModel):
    """Request to execute a workflow."""

    model_config = ConfigDict(extra="forbid")

    inputs: dict[str, str] = Field(
        default_factory=dict,
        description="Input variables for the workflow.",
    )
    task: str | None = Field(
        default=None,
        description="Primary task description -- substituted for $ARGUMENTS in phase prompts.",
    )
    provider: str = Field(
        default="claude",
        description=(
            "Agent provider to use. Currently ignored by execute(); "
            "sending this field has no effect."
        ),
        deprecated=True,
    )
    max_budget_usd: float | None = Field(
        default=None,
        description=(
            "Maximum budget in USD. Currently ignored by execute(); "
            "sending this field has no effect."
        ),
        deprecated=True,
    )


class ExecuteWorkflowResponse(BaseModel):
    """Response after starting workflow execution."""

    execution_id: str
    workflow_id: str
    status: str = "started"
    message: str = "Workflow execution started"


class ExecutionStatusResponse(BaseModel):
    """Response for execution status check."""

    execution_id: str
    workflow_id: str
    status: str
    current_phase: str | None = None
    completed_phases: int = 0
    total_phases: int = 0
    started_at: str | None = None
    completed_at: str | None = None
    error: str | None = None


# -- Helpers ------------------------------------------------------------------


def _to_datetime(value: datetime | str | None) -> datetime | None:
    """Convert datetime or ISO string to datetime, handling common variants safely."""
    if value is None:
        return None
    if isinstance(value, str):
        raw = value.strip()
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        try:
            return datetime.fromisoformat(raw)
        except ValueError:
            logger.warning("Failed to parse datetime from value %r", value)
            return None
    return value


# -- Service functions --------------------------------------------------------


async def execute(
    workflow_id: str,
    inputs: dict[str, str] | None = None,
    execution_id: str | None = None,
    task: str | None = None,
    tenant_id: str | None = None,
    auth: AuthContext | None = None,
) -> Result[ExecutionSummary, WorkflowError]:
    """Execute a workflow.

    Args:
        workflow_id: ID of the workflow template to execute.
        inputs: Input variables for the workflow.
        execution_id: Optional execution ID (auto-generated if omitted).
        task: Optional primary task description.
        tenant_id: Optional tenant ID for multi-tenant deployments.
        auth: Optional authentication context.

    Returns:
        Ok(ExecutionSummary) on success, Err(WorkflowError) on failure.
    """
    from syn_domain.contexts.orchestration.domain.commands.ExecuteWorkflowCommand import (
        ExecuteWorkflowCommand,
    )
    from syn_domain.contexts.orchestration.slices.execute_workflow.errors import (
        WorkflowNotFoundError,
    )
    from syn_domain.contexts.orchestration.slices.execute_workflow.ExecuteWorkflowHandler import (
        ExecuteWorkflowHandler,
    )

    await ensure_connected()
    manager = get_projection_mgr()
    detail = await manager.workflow_detail.get_by_id(workflow_id)
    workflow_name = detail.name if detail else ""

    from syn_api._wiring import get_workflow_repo

    processor = await get_execution_processor()
    handler = ExecuteWorkflowHandler(
        processor=processor,
        workflow_repository=get_workflow_repo(),
    )

    try:
        cmd = ExecuteWorkflowCommand(
            aggregate_id=workflow_id,
            inputs=inputs or {},
            execution_id=execution_id,
            task=task,
        )
        result = await handler.handle(cmd)
    except WorkflowNotFoundError:
        return Err(WorkflowError.NOT_FOUND, message=f"Workflow {workflow_id} not found")
    except Exception:
        logger.exception("Workflow execution error for %s", workflow_id)
        return Err(WorkflowError.EXECUTION_FAILED, message="internal error")

    return Ok(
        ExecutionSummary(
            workflow_execution_id=result.execution_id,
            workflow_id=workflow_id,
            workflow_name=workflow_name,
            status=result.status,
            completed_phases=result.metrics.completed_phases,
            total_phases=result.metrics.total_phases,
            total_tokens=result.metrics.total_tokens,
            total_cost_usd=result.metrics.total_cost_usd,
            error_message=result.error_message,
        )
    )


# -- HTTP Endpoints -----------------------------------------------------------


@router.post("/{workflow_id}/execute", response_model=ExecuteWorkflowResponse)
async def execute_workflow_endpoint(
    workflow_id: str,
    request: ExecuteWorkflowRequest,
    background_tasks: BackgroundTasks,
) -> ExecuteWorkflowResponse:
    """Start workflow execution in background."""
    execution_id = f"exec-{uuid4().hex[:12]}"

    async def _run() -> None:
        result = await execute(
            workflow_id=workflow_id,
            inputs=request.inputs,
            execution_id=execution_id,
            task=request.task,
        )
        if isinstance(result, Err):
            logger.error(
                "Workflow execution failed",
                extra={
                    "execution_id": execution_id,
                    "workflow_id": workflow_id,
                    "error": result.message,
                },
            )

    background_tasks.add_task(_run)
    logger.info(
        "Started workflow execution",
        extra={
            "execution_id": execution_id,
            "workflow_id": workflow_id,
            "provider": request.provider,
        },
    )
    return ExecuteWorkflowResponse(
        execution_id=execution_id,
        workflow_id=workflow_id,
        status="started",
        message=f"Workflow execution started with provider '{request.provider}'",
    )


@router.get("/{workflow_id}/executions/{execution_id}", response_model=ExecutionStatusResponse)
async def get_execution_status_endpoint(
    workflow_id: str,
    execution_id: str,
) -> ExecutionStatusResponse:
    """Get the status of a workflow execution."""
    from syn_api.prefix_resolver import resolve_or_raise

    from .queries import get_detail

    mgr = get_projection_mgr()
    execution_id = await resolve_or_raise(
        mgr.store, "workflow_execution_details", execution_id, "Execution"
    )
    result = await get_detail(execution_id)
    if isinstance(result, Err):
        raise HTTPException(status_code=404, detail=f"Execution {execution_id} not found")

    detail = result.value
    if detail.workflow_id != workflow_id:
        raise HTTPException(
            status_code=404,
            detail=f"Execution {execution_id} not found for workflow {workflow_id}",
        )

    current_phase = None
    completed_phases = 0
    total_phases = len(detail.phases) if detail.phases else 0
    for phase in detail.phases or []:
        if phase.status == "running":
            current_phase = phase.phase_id
        if phase.status == "completed":
            completed_phases += 1

    return ExecutionStatusResponse(
        execution_id=detail.workflow_execution_id,
        workflow_id=detail.workflow_id,
        status=detail.status,
        current_phase=current_phase,
        completed_phases=completed_phases,
        total_phases=total_phases,
        started_at=str(_to_datetime(detail.started_at)) if detail.started_at else None,
        completed_at=str(_to_datetime(detail.completed_at)) if detail.completed_at else None,
        error=detail.error_message,
    )


@router.get("/executions/active")
async def list_active_executions_endpoint(
    limit: int = Query(20, ge=1, le=100),
) -> list[ExecutionStatusResponse]:
    """List all active (non-completed) executions."""
    from .queries import list_active

    result = await list_active(limit=limit)
    if isinstance(result, Err):
        return []

    return [
        ExecutionStatusResponse(
            execution_id=s.workflow_execution_id,
            workflow_id=s.workflow_id,
            status=s.status,
            current_phase=None,
            completed_phases=s.completed_phases,
            total_phases=s.total_phases,
            started_at=str(_to_datetime(s.started_at)) if s.started_at else None,
            completed_at=str(_to_datetime(s.completed_at)) if s.completed_at else None,
            error=s.error_message,
        )
        for s in result.value
    ]
