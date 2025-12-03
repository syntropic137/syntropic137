"""Workflow execution API endpoint.

This module provides the API endpoint to trigger workflow execution
using the AgenticWorkflowExecutor. Events are streamed to SSE in real-time.
"""

from __future__ import annotations

import logging
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query

from aef_dashboard.models.schemas import (
    ExecuteWorkflowRequest,
    ExecuteWorkflowResponse,
    ExecutionStatusResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/workflows", tags=["execution"])

# In-memory execution tracking
# In production, use Redis or database
_active_executions: dict[str, dict] = {}


@router.post("/{workflow_id}/execute", response_model=ExecuteWorkflowResponse)
async def execute_workflow(
    workflow_id: str,
    request: ExecuteWorkflowRequest,
    background_tasks: BackgroundTasks,
) -> ExecuteWorkflowResponse:
    """Start workflow execution.

    This endpoint triggers asynchronous workflow execution using the
    AgenticWorkflowExecutor. Events are streamed to the SSE endpoint
    in real-time as execution progresses.

    Args:
        workflow_id: The ID of the workflow to execute.
        request: Execution configuration (inputs, provider, budget).
        background_tasks: FastAPI background tasks handler.

    Returns:
        ExecuteWorkflowResponse with execution_id and status.

    Raises:
        HTTPException: If workflow not found or execution fails to start.
    """
    # Import here to avoid circular imports and allow worktree imports
    from aef_dashboard.services.execution import ExecutionService

    execution_id = str(uuid4())

    # Track execution
    _active_executions[execution_id] = {
        "workflow_id": workflow_id,
        "status": "starting",
        "current_phase": None,
        "completed_phases": 0,
        "total_phases": 0,
        "started_at": None,
        "completed_at": None,
        "error": None,
    }

    # Start execution in background
    service = ExecutionService()
    background_tasks.add_task(
        service.run_workflow,
        execution_id=execution_id,
        workflow_id=workflow_id,
        inputs=request.inputs,
        provider=request.provider,
        max_budget_usd=request.max_budget_usd,
        execution_tracker=_active_executions,
    )

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
    """Get the status of a workflow execution.

    Args:
        workflow_id: The workflow ID.
        execution_id: The execution ID returned from execute.

    Returns:
        ExecutionStatusResponse with current status.

    Raises:
        HTTPException: If execution not found.
    """
    if execution_id not in _active_executions:
        raise HTTPException(
            status_code=404,
            detail=f"Execution {execution_id} not found",
        )

    exec_info = _active_executions[execution_id]

    if exec_info["workflow_id"] != workflow_id:
        raise HTTPException(
            status_code=404,
            detail=f"Execution {execution_id} not found for workflow {workflow_id}",
        )

    return ExecutionStatusResponse(
        execution_id=execution_id,
        workflow_id=workflow_id,
        status=exec_info["status"],
        current_phase=exec_info.get("current_phase"),
        completed_phases=exec_info.get("completed_phases", 0),
        total_phases=exec_info.get("total_phases", 0),
        started_at=exec_info.get("started_at"),
        completed_at=exec_info.get("completed_at"),
        error=exec_info.get("error"),
    )


@router.get("/executions/active")
async def list_active_executions(
    limit: int = Query(20, ge=1, le=100),
) -> list[ExecutionStatusResponse]:
    """List all active (non-completed) executions.

    Returns:
        List of active execution statuses.
    """
    active = [
        ExecutionStatusResponse(
            execution_id=exec_id,
            workflow_id=info["workflow_id"],
            status=info["status"],
            current_phase=info.get("current_phase"),
            completed_phases=info.get("completed_phases", 0),
            total_phases=info.get("total_phases", 0),
            started_at=info.get("started_at"),
            completed_at=info.get("completed_at"),
            error=info.get("error"),
        )
        for exec_id, info in _active_executions.items()
        if info["status"] not in ("completed", "failed")
    ]

    return active[:limit]
