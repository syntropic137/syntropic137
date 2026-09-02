"""Execution control endpoints and service functions.

Pause, resume, cancel, inject, and state inspection for running executions.
"""

from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from syn_api._wiring import get_controller
from syn_api.types import (
    ControlResult,
    Err,
    ExecutionError,
    Ok,
    Result,
)

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
    """Response from a control command.

    Pause/resume/cancel act by enqueueing a signal for the executor to pick
    up at its next yield point - this endpoint returns before that signal
    is processed. `state` is therefore the state observed *before* the
    signal was enqueued, not a confirmation that the transition happened.
    Check `state_pending`: if True, `state` is unconfirmed and the actual
    transition has not been observed by this response - poll
    `GET /executions/{execution_id}/state` to see it land. If False, no
    signal was queued (the command was rejected, or - for inject - the
    command never changes state), so `state` is the accurate current state.
    (#1062)
    """

    success: bool
    execution_id: str
    state: str
    state_pending: bool = False
    message: str | None = None
    error: str | None = None


class StateResponse(BaseModel):
    """Response with execution state."""

    execution_id: str
    state: str


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
                state_pending=domain_result.state_pending,
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
                state_pending=domain_result.state_pending,
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
                state_pending=domain_result.state_pending,
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
                state_pending=domain_result.state_pending,
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
        state_pending=ctrl.state_pending,
        message=ctrl.message,
    )


@router.post("/executions/{execution_id}/pause", response_model=ControlResponse)
async def pause_execution_endpoint(
    execution_id: str,
    request: PauseRequest | None = None,
) -> ControlResponse:
    """Pause a running execution.

    Asynchronous: enqueues a pause signal for the executor to pick up at its
    next yield point and returns immediately. The response's `state` is the
    state observed before the signal was enqueued - check `state_pending`
    before treating it as confirmed (#1062).
    """
    execution_id = await _resolve_execution_id(execution_id)
    result = await pause(execution_id, reason=request.reason if request else None)
    return await _handle_control_result(result, "pause")


@router.post("/executions/{execution_id}/resume", response_model=ControlResponse)
async def resume_execution_endpoint(execution_id: str) -> ControlResponse:
    """Resume a paused execution.

    Asynchronous: enqueues a resume signal for the executor to pick up at
    its next yield point and returns immediately. The response's `state` is
    the state observed before the signal was enqueued - check
    `state_pending` before treating it as confirmed (#1062).
    """
    execution_id = await _resolve_execution_id(execution_id)
    result = await resume(execution_id)
    return await _handle_control_result(result, "resume")


@router.post("/executions/{execution_id}/cancel", response_model=ControlResponse)
async def cancel_execution_endpoint(
    execution_id: str,
    request: CancelRequest | None = None,
) -> ControlResponse:
    """Cancel a running or paused execution.

    Asynchronous: enqueues a cancel signal for the executor to pick up at
    its next yield point and returns immediately, before the cancellation
    is observed. The response's `state` is the state observed before the
    signal was enqueued, not a confirmation that the execution has actually
    been cancelled - check `state_pending`, or poll
    `GET /executions/{execution_id}/state` for the confirmed state (#1062).
    """
    execution_id = await _resolve_execution_id(execution_id)
    result = await cancel(execution_id, reason=request.reason if request else None)
    return await _handle_control_result(result, "cancel")


@router.post("/executions/{execution_id}/inject", response_model=ControlResponse)
async def inject_context_endpoint(
    execution_id: str,
    request: InjectRequest,
) -> ControlResponse:
    """Inject a message into the execution context.

    Asynchronous: enqueues the message for the executor to pick up at its
    next yield point. Injection never changes execution state, so `state`
    is accurate immediately (`state_pending` is always False here).
    """
    execution_id = await _resolve_execution_id(execution_id)
    result = await inject(execution_id, message=request.message, role=request.role)
    return await _handle_control_result(result, "inject")


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
