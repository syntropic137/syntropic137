"""Workflow execution API endpoint.

This module provides the API endpoint to trigger workflow execution
using the WorkflowExecutionEngine. Status is queried from the
WorkflowExecutionDetailProjection which is updated via event sourcing.

Architecture:
  POST /execute → ExecutionService.run_workflow() → WorkflowExecutionEngine
                                                         ↓
                                               Event Store (persisted)
                                                         ↓
                                           WorkflowExecutionDetailProjection
                                                         ↓
  GET /status  → ExecutionService.get_execution_status() ←────────────┘
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query

from aef_dashboard.models.schemas import (
    ExecuteWorkflowRequest,
    ExecuteWorkflowResponse,
    ExecutionStatusResponse,
)

if TYPE_CHECKING:
    from aef_domain.contexts.workflows.domain.read_models.workflow_execution_detail import (
        WorkflowExecutionDetail,
    )

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/workflows", tags=["execution"])


@router.post("/{workflow_id}/execute", response_model=ExecuteWorkflowResponse)
async def execute_workflow(
    workflow_id: str,
    request: ExecuteWorkflowRequest,
    background_tasks: BackgroundTasks,
) -> ExecuteWorkflowResponse:
    """Start workflow execution.

    This endpoint triggers asynchronous workflow execution using the
    WorkflowExecutionEngine. Events flow through the event store and
    update the WorkflowExecutionDetailProjection in real-time.

    Query status via GET /workflows/{workflow_id}/executions/{execution_id}

    Args:
        workflow_id: The ID of the workflow to execute.
        request: Execution configuration (inputs, provider, budget).
        background_tasks: FastAPI background tasks handler.

    Returns:
        ExecuteWorkflowResponse with execution_id and status.

    Raises:
        HTTPException: If workflow not found or execution fails to start.
    """
    # Import here to avoid circular imports
    from aef_dashboard.services.execution import ExecutionService

    execution_id = str(uuid4())

    # Start execution in background - no in-memory tracking needed
    # Status is persisted via events → WorkflowExecutionDetailProjection
    service = ExecutionService()
    background_tasks.add_task(
        service.run_workflow,
        execution_id=execution_id,
        workflow_id=workflow_id,
        inputs=request.inputs,
        provider=request.provider,
        max_budget_usd=request.max_budget_usd,
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

    Queries the WorkflowExecutionDetailProjection which is updated
    in real-time as events flow through the event store.

    Args:
        workflow_id: The workflow ID.
        execution_id: The execution ID returned from execute.

    Returns:
        ExecutionStatusResponse with current status.

    Raises:
        HTTPException: If execution not found.
    """
    from aef_dashboard.services.execution import ExecutionService

    service = ExecutionService()
    detail = await service.get_execution_status(execution_id)

    if detail is None:
        raise HTTPException(
            status_code=404,
            detail=f"Execution {execution_id} not found",
        )

    if detail.workflow_id != workflow_id:
        raise HTTPException(
            status_code=404,
            detail=f"Execution {execution_id} not found for workflow {workflow_id}",
        )

    # Map projection detail to API response
    return ExecutionStatusResponse(
        execution_id=detail.execution_id,
        workflow_id=detail.workflow_id,
        status=detail.status,
        current_phase=_get_current_phase(detail),
        completed_phases=_count_completed_phases(detail),
        total_phases=len(detail.phases) if detail.phases else 0,
        started_at=detail.started_at,
        completed_at=detail.completed_at,
        error=detail.error_message,
    )


def _get_current_phase(detail: WorkflowExecutionDetail) -> str | None:
    """Get the currently running phase ID from detail."""
    if not detail.phases:
        return None
    for phase in detail.phases:
        if phase.get("status") == "running":
            return phase.get("phase_id")
    return None


def _count_completed_phases(detail: WorkflowExecutionDetail) -> int:
    """Count completed phases from detail."""
    if not detail.phases:
        return 0
    return sum(1 for p in detail.phases if p.get("status") == "completed")


@router.get("/executions/active")
async def list_active_executions(
    limit: int = Query(20, ge=1, le=100),
) -> list[ExecutionStatusResponse]:
    """List all active (non-completed) executions.

    Queries the WorkflowExecutionListProjection for running executions.

    Returns:
        List of active execution statuses.
    """
    from aef_adapters.projections import get_projection_manager

    manager = get_projection_manager()

    # Query executions with status 'running' or 'paused'
    # The list projection provides a filtered view
    all_executions = await manager.workflow_execution_list.list_recent(limit=limit * 2)

    active = []
    for exec_summary in all_executions:
        if exec_summary.status in ("running", "paused", "starting"):
            # Get full detail for the response
            detail = await manager.workflow_execution_detail.get_by_id(exec_summary.execution_id)
            if detail:
                active.append(
                    ExecutionStatusResponse(
                        execution_id=detail.execution_id,
                        workflow_id=detail.workflow_id,
                        status=detail.status,
                        current_phase=_get_current_phase(detail),
                        completed_phases=_count_completed_phases(detail),
                        total_phases=len(detail.phases) if detail.phases else 0,
                        started_at=detail.started_at,
                        completed_at=detail.completed_at,
                        error=detail.error_message,
                    )
                )
            if len(active) >= limit:
                break

    return active
