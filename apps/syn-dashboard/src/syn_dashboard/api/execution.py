"""Workflow execution API endpoint — thin wrapper over syn_api."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Query

import syn_api.v1.executions as ex
from syn_api.types import Err
from syn_dashboard.models.schemas import (
    ExecuteWorkflowRequest,
    ExecuteWorkflowResponse,
    ExecutionStatusResponse,
)

if TYPE_CHECKING:
    from datetime import datetime as DatetimeType


def _to_datetime(value: DatetimeType | str | None) -> DatetimeType | None:
    """Convert datetime or ISO string to datetime."""
    if value is None:
        return None
    if isinstance(value, str):
        from datetime import datetime

        return datetime.fromisoformat(value)
    return value


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/workflows", tags=["execution"])


@router.post("/{workflow_id}/execute", response_model=ExecuteWorkflowResponse)
async def execute_workflow(
    workflow_id: str,
    request: ExecuteWorkflowRequest,
    background_tasks: BackgroundTasks,
) -> ExecuteWorkflowResponse:
    """Start workflow execution in background."""
    execution_id = str(uuid4())

    async def _run() -> None:
        await ex.execute(
            workflow_id=workflow_id,
            inputs=request.inputs,
            execution_id=execution_id,
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
async def get_execution_status(
    workflow_id: str,
    execution_id: str,
) -> ExecutionStatusResponse:
    """Get the status of a workflow execution."""
    from fastapi import HTTPException

    result = await ex.get_detail(execution_id)

    if isinstance(result, Err):
        raise HTTPException(status_code=404, detail=f"Execution {execution_id} not found")

    detail = result.value
    if detail.workflow_id != workflow_id:
        raise HTTPException(
            status_code=404,
            detail=f"Execution {execution_id} not found for workflow {workflow_id}",
        )

    # Find current phase
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
        started_at=_to_datetime(detail.started_at),
        completed_at=_to_datetime(detail.completed_at),
        error=detail.error_message,
    )


@router.get("/executions/active")
async def list_active_executions(
    limit: int = Query(20, ge=1, le=100),
) -> list[ExecutionStatusResponse]:
    """List all active (non-completed) executions."""
    result = await ex.list_active(limit=limit)

    if isinstance(result, Err):
        return []

    active = []
    for s in result.value:
        active.append(
            ExecutionStatusResponse(
                execution_id=s.workflow_execution_id,
                workflow_id=s.workflow_id,
                status=s.status,
                current_phase=None,
                completed_phases=s.completed_phases,
                total_phases=s.total_phases,
                started_at=_to_datetime(s.started_at),
                completed_at=_to_datetime(s.completed_at),
                error=s.error_message,
            )
        )

    return active
