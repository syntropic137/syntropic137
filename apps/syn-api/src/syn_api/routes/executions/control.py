"""Execution control endpoints and service functions.

Cancel, inject, and state inspection for running executions.
"""

from __future__ import annotations

import asyncio
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


#: How long a prefix miss waits to learn whether the read model is rebuilding.
#: The probe reads the database; past this the miss stays the 404 it always was.
_REBUILD_PROBE_TIMEOUT_S = 2.0


class ExecutionReadModelRebuilding(HTTPException):
    """409: a prefix the execution read model cannot expand while it is rebuilt (#1555).

    Not a 404, because the execution may well exist: the read model that maps
    prefixes to ids has not replayed it yet. The full id does not need that read
    model, so the detail says to use it.
    """

    def __init__(self, partial_id: str) -> None:
        super().__init__(
            status_code=409,
            detail=(
                f"Cannot resolve execution id prefix '{partial_id}': the execution read "
                "model is rebuilding and has not replayed every execution yet. Retry once "
                "it catches up (see /health), or pass the full execution id, which is "
                "resolved from the event store."
            ),
        )


async def _resolve_execution_id(execution_id: str) -> str:
    """The full id of the execution a command names, or raise why there is none.

    A full id is answered by the event store, which is authoritative, so a
    command keeps working while `workflow_execution_details` is being rebuilt
    (#1555). Only a prefix needs that read model, to expand it; a prefix it
    cannot find while rebuilding is `ExecutionReadModelRebuilding`, not 404.
    """
    from syn_api._wiring import get_projection_mgr, get_workflow_execution_repository
    from syn_api.prefix_resolver import resolve_or_raise

    if await get_workflow_execution_repository().exists(execution_id):
        return execution_id
    try:
        return await resolve_or_raise(
            get_projection_mgr().store, "workflow_execution_details", execution_id, "Execution"
        )
    except HTTPException as miss:
        if miss.status_code == 404 and await _execution_read_model_rebuilding():
            raise ExecutionReadModelRebuilding(execution_id) from miss
        raise


async def _execution_read_model_rebuilding() -> bool:
    """Whether `workflow_execution_details` is replaying history right now.

    False when that cannot be told - no subscription, or a probe that failed or
    hung - so a miss stays the 404 it was before this question was asked.
    """
    from syn_api.services.lifecycle import _state
    from syn_domain.contexts.orchestration.slices.get_execution_detail.projection import (
        WorkflowExecutionDetailProjection,
    )

    service = _state.subscription_service
    if service is None:
        return False
    try:
        lag = await asyncio.wait_for(
            service.describe_read_model_lag(), timeout=_REBUILD_PROBE_TIMEOUT_S
        )
    except Exception:
        logger.warning("Read model lag probe failed; reporting a prefix miss as 404", exc_info=True)
        return False
    if lag is None or not lag.is_catching_up:
        return False
    name = WorkflowExecutionDetailProjection.PROJECTION_NAME
    return any(behind.projection == name for behind in lag.lagging_projections)


# =============================================================================
# Request/Response Models
# =============================================================================


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


# =============================================================================
# Service functions (importable by tests)
# =============================================================================


async def cancel(
    execution_id: str,
    reason: str | None = None,
) -> Result[ControlResult, ExecutionError]:
    """Cancel a running execution."""
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
        try:
            state = await controller.get_state(execution_id)
        except Exception as exc:
            # A failed READ is not an absent execution. The controller loads
            # the aggregate from the event store now, so an outage raises here
            # where it previously could not. Mapping it to NOT_FOUND made the
            # endpoint answer 200 with state="unknown" - a successful-looking
            # reply to a question nothing could answer.
            logger.warning("could not read control state for %s", execution_id, exc_info=True)
            return Err(
                ExecutionError.STORE_UNAVAILABLE,
                message=(
                    f"Could not read the state of execution {execution_id}: the event "
                    f"store could not be read ({type(exc).__name__}). This is not a "
                    "statement that the execution is absent."
                ),
            )
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
        # Anything else reaching here is also a failure to answer, not an
        # absence. NOT_FOUND was the old catch-all and it is what made an
        # outage indistinguishable from a missing execution.
        logger.warning("control state lookup failed for %s", execution_id, exc_info=True)
        return Err(ExecutionError.STORE_UNAVAILABLE, message=str(e))


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


@router.post("/executions/{execution_id}/cancel", response_model=ControlResponse)
async def cancel_execution_endpoint(
    execution_id: str,
    request: CancelRequest | None = None,
) -> ControlResponse:
    """Cancel an execution, or withdraw a start still queued for one (#1650)."""
    reason = request.reason if request else None
    try:
        resolved = await _resolve_execution_id(execution_id)
    except HTTPException as not_found:
        # A rebuild hides queued starts' executions no more than started ones,
        # so a prefix it could not expand is still offered to the withdrawal.
        if not_found.status_code != 404 and not isinstance(
            not_found, ExecutionReadModelRebuilding
        ):
            raise
        withdrawn = await _withdraw_queued(execution_id, reason)
        if withdrawn is None:
            raise
        return withdrawn
    result = await cancel(resolved, reason=reason)
    return await _handle_control_result(result, "cancel")


async def _withdraw_queued(execution_id: str, reason: str | None) -> ControlResponse | None:
    """Withdraw an accepted start with no execution yet; None if there is none.

    A queued start has no `workflow_execution_details` row, which is what made
    cancelling it a 404. Its request is withdrawn instead: durably, so neither
    the task waiting for a slot nor a restart starts it.
    """
    from syn_api._wiring import get_projection_mgr
    from syn_api.routes.executions.direct_start import withdraw_execution_request
    from syn_api.routes.executions.queued_start import queued_execution_id

    full_id = await queued_execution_id(get_projection_mgr(), execution_id)
    if full_id is None or not await withdraw_execution_request(full_id, reason):
        return None
    # Both projections asked above lag the execution's stream. A run that
    # started before the withdrawal landed is cancelled as any started run is,
    # never reported as one that "will not run" (#1650 verification).
    if await get_controller().get_state(full_id) is not None:
        return await _handle_control_result(await cancel(full_id, reason=reason), "cancel")
    return ControlResponse(
        success=True,
        execution_id=full_id,
        state="cancelled",
        message="Withdrawn before it started: it will not run",
    )


@router.post("/executions/{execution_id}/inject", response_model=ControlResponse)
async def inject_context_endpoint(
    execution_id: str,
    request: InjectRequest,
) -> ControlResponse:
    """Inject a message into the execution context."""
    execution_id = await _resolve_execution_id(execution_id)
    result = await inject(execution_id, message=request.message, role=request.role)
    return await _handle_control_result(result, "inject")


@router.get("/executions/{execution_id}/state", response_model=StateResponse)
async def get_execution_state_endpoint(execution_id: str) -> StateResponse:
    """Get current execution state."""
    execution_id = await _resolve_execution_id(execution_id)
    result = await get_state(execution_id)

    if isinstance(result, Err):
        # A store failure must NOT render as a 200 carrying state="unknown".
        # That is a successful-looking answer to a question nothing could
        # answer, and a caller polling this endpoint would read it as fact.
        if result.error == ExecutionError.STORE_UNAVAILABLE:
            raise HTTPException(status_code=503, detail=result.message)
        # NOT_FOUND keeps its previous shape: the resolver above already
        # established the execution exists, so this is the narrower case of an
        # execution with no control state yet.
        return StateResponse(execution_id=execution_id, state="unknown")

    return StateResponse(execution_id=execution_id, state=result.value.get("state", "unknown"))
