"""Execution control endpoints and service functions.

Pause, resume, cancel, inject, and state inspection for running executions.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Literal
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

from syn_api._wiring import get_controller
from syn_api.types import (
    ControlResult,
    Err,
    ExecutionError,
    Ok,
    Result,
)

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration import RetryPlan

logger = logging.getLogger(__name__)

router = APIRouter(tags=["control"])


async def _resolve_execution_id(execution_id: str) -> str:
    """Resolve a (possibly partial) execution ID via prefix matching."""
    from syn_api._wiring import get_projection_mgr
    from syn_api.prefix_resolver import resolve_or_raise

    mgr = get_projection_mgr()
    return await resolve_or_raise(
        mgr.store, "workflow_execution_details", execution_id, "Execution"
    )


# =============================================================================
# Request/Response Models
# =============================================================================


class PauseRequest(BaseModel):
    """Request to pause an execution."""

    reason: str | None = None


class CancelRequest(BaseModel):
    """Request to cancel an execution."""

    reason: str | None = None


class InjectRequest(BaseModel):
    """Request to inject context into an execution."""

    message: str
    role: Literal["user", "system"] = "user"


class ControlResponse(BaseModel):
    """Response from a control command."""

    success: bool
    execution_id: str
    state: str
    message: str | None = None
    error: str | None = None


class StateResponse(BaseModel):
    """Response with execution state."""

    execution_id: str
    state: str


class RetryResponse(BaseModel):
    """Response from retrying a failed execution.

    Two execution ids on purpose. A retry is a NEW execution (#1335) - the
    failed one stays failed and keeps the cost it incurred - so a caller that
    was handed only one id would either poll the corpse or lose the thread
    back to it.
    """

    execution_id: str
    """The new execution, now running."""

    retried_execution_id: str
    """The failed execution it continues."""

    workflow_id: str
    phase_id: str
    """The phase the new execution starts at: the one that failed."""

    inherited_phase_ids: list[str]
    """Phases it does NOT re-run, whose outputs it starts with."""

    status: str


# =============================================================================
# Service functions (importable by tests)
# =============================================================================


async def pause(
    execution_id: str,
    reason: str | None = None,
) -> Result[ControlResult, ExecutionError]:
    """Pause a running execution at the next yield point."""
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
) -> Result[ControlResult, ExecutionError]:
    """Resume a paused execution."""
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
) -> Result[ControlResult, ExecutionError]:
    """Cancel a running or paused execution."""
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
) -> Result[ControlResult, ExecutionError]:
    """Inject a message into an execution's agent context."""
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
) -> Result[dict[str, str], ExecutionError]:
    """Get the current control state of an execution."""
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


async def plan_retry(execution_id: str) -> Result[RetryPlan, ExecutionError]:
    """Work out how this execution would be continued, without starting anything.

    Separate from the start so the route can answer 404 and 409 before any
    work is dispatched into a background task, where an error would only ever
    reach a log.
    """
    from syn_adapters.storage.repositories import get_workflow_execution_repository

    try:
        aggregate = await get_workflow_execution_repository().get_by_id(execution_id)
    except Exception as e:
        logger.exception("Could not load execution %s for retry", execution_id)
        return Err(ExecutionError.NOT_FOUND, message=str(e))

    if aggregate is None:
        return Err(ExecutionError.NOT_FOUND, message=f"Execution {execution_id} not found")

    try:
        plan = aggregate.retry_plan
    except ValueError as e:
        return Err(ExecutionError.INVALID_STATE, message=str(e))

    if plan is None:
        return Err(
            ExecutionError.INVALID_STATE,
            message=(
                f"Execution {execution_id} is {aggregate.status.value} and names no failed "
                f"phase; only an execution that failed inside a phase can be retried"
            ),
        )
    return Ok(plan)


# =============================================================================
# HTTP Endpoints
# =============================================================================


async def _handle_control_result(
    result: Result[ControlResult, ExecutionError], _action: str = ""
) -> ControlResponse:
    """Convert control result to HTTP response."""
    if isinstance(result, Err):
        raise HTTPException(status_code=400, detail=result.message)

    ctrl = result.value
    if not ctrl.success:
        raise HTTPException(status_code=400, detail=ctrl.error)

    return ControlResponse(
        success=ctrl.success,
        execution_id=ctrl.execution_id,
        state=ctrl.new_state,
        message=ctrl.message,
    )


@router.post("/executions/{execution_id}/pause", response_model=ControlResponse)
async def pause_execution_endpoint(
    execution_id: str,
    request: PauseRequest | None = None,
) -> ControlResponse:
    """Pause a running execution."""
    execution_id = await _resolve_execution_id(execution_id)
    result = await pause(execution_id, reason=request.reason if request else None)
    return await _handle_control_result(result, "pause")


@router.post("/executions/{execution_id}/resume", response_model=ControlResponse)
async def resume_execution_endpoint(execution_id: str) -> ControlResponse:
    """Resume a paused execution."""
    execution_id = await _resolve_execution_id(execution_id)
    result = await resume(execution_id)
    return await _handle_control_result(result, "resume")


@router.post("/executions/{execution_id}/cancel", response_model=ControlResponse)
async def cancel_execution_endpoint(
    execution_id: str,
    request: CancelRequest | None = None,
) -> ControlResponse:
    """Cancel a running or paused execution."""
    execution_id = await _resolve_execution_id(execution_id)
    result = await cancel(execution_id, reason=request.reason if request else None)
    return await _handle_control_result(result, "cancel")


@router.post("/executions/{execution_id}/inject", response_model=ControlResponse)
async def inject_context_endpoint(
    execution_id: str,
    request: InjectRequest,
) -> ControlResponse:
    """Inject a message into the execution context."""
    execution_id = await _resolve_execution_id(execution_id)
    result = await inject(execution_id, message=request.message, role=request.role)
    return await _handle_control_result(result, "inject")


@router.post("/executions/{execution_id}/retry", response_model=RetryResponse)
async def retry_execution_endpoint(
    execution_id: str,
    background_tasks: BackgroundTasks,
) -> RetryResponse:
    """Run a failed execution again from the phase it failed in (#1335).

    WHY THIS EXISTS. A phase can lose its transport after the work is done -
    a codex `verify` phase whose stream ended without `turn.completed` is the
    case that prompted this. The processor is right to refuse the phase: with
    no usage numbers it cannot complete one without corrupting cost
    attribution. What was wrong was the blast radius, which was the entire
    run: three of them, and the finished `implement` phase discarded with
    each. This bounds the loss to the phase that died.

    The new execution inherits the earlier phases' artifacts from the failed
    one, so the retried phase opens the same `artifacts/input/` and therefore
    - for verify - checks out the same branch at the same head.
    """
    from syn_api.routes.executions.commands import execute

    execution_id = await _resolve_execution_id(execution_id)
    planned = await plan_retry(execution_id)
    if isinstance(planned, Err):
        status_code = 404 if planned.error is ExecutionError.NOT_FOUND else 409
        raise HTTPException(status_code=status_code, detail=planned.message)

    plan = planned.value
    retry_id = f"exec-{uuid4().hex[:12]}"

    async def _run() -> None:
        try:
            result = await execute(
                workflow_id=plan.workflow_id,
                inputs=dict(plan.inputs),
                execution_id=retry_id,
                repos=list(plan.repos),
                resume=plan.resume,
            )
            if isinstance(result, Err):
                logger.error(
                    "Retry execution failed",
                    extra={
                        "execution_id": retry_id,
                        "retried_execution_id": execution_id,
                        "error": result.message,
                    },
                )
        except Exception:
            logger.exception(
                "Retry execution raised exception",
                extra={"execution_id": retry_id, "retried_execution_id": execution_id},
            )

    background_tasks.add_task(_run)
    logger.info(
        "Retrying execution",
        extra={
            "execution_id": retry_id,
            "retried_execution_id": execution_id,
            "phase_id": plan.resume.phase_id,
        },
    )
    return RetryResponse(
        execution_id=retry_id,
        retried_execution_id=execution_id,
        workflow_id=plan.workflow_id,
        phase_id=plan.resume.phase_id,
        inherited_phase_ids=list(plan.resume.inherited.phase_ids),
        status="started",
    )


@router.get("/executions/{execution_id}/state", response_model=StateResponse)
async def get_execution_state_endpoint(execution_id: str) -> StateResponse:
    """Get current execution state."""
    from syn_api._wiring import get_projection_mgr
    from syn_api.prefix_resolver import resolve_or_raise

    mgr = get_projection_mgr()
    execution_id = await resolve_or_raise(
        mgr.store, "workflow_execution_details", execution_id, "Execution"
    )
    result = await get_state(execution_id)

    state_val = "unknown"
    if not isinstance(result, Err):
        state_val = result.value.get("state", "unknown")

    return StateResponse(execution_id=execution_id, state=state_val)
