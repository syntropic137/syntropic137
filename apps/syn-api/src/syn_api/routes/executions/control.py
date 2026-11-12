"""Execution control endpoints and service functions.

Cancel and state inspection for running executions. Inject is refused: nothing
delivers a message into a running agent yet (#1530).
"""

from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

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

    False when that cannot be told, so a miss stays the 404 it was before this
    question was asked. See `services.read_model_status` for what counts.
    """
    from syn_api.services.read_model_status import read_model_status
    from syn_domain.contexts.orchestration.slices.get_execution_detail.projection import (
        WorkflowExecutionDetailProjection,
    )

    status = await read_model_status(WorkflowExecutionDetailProjection.PROJECTION_NAME)
    return status.rebuilding


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
    state: str = Field(
        description=(
            "The execution's state when the command was accepted. For a queued "
            "signal (`applied` is false) this is the state BEFORE the command takes "
            "effect: re-read `GET /executions/{execution_id}` until it reads "
            "`cancelled` (#1062)."
        )
    )
    applied: bool = Field(
        description=(
            "Whether the command has already taken effect. False when a signal was "
            "queued for the executor to act on, as for a cancel of a running "
            "execution; true when nothing is left to happen, as for a queued start "
            "that was withdrawn and will not run. A later `GET /executions/{execution_id}` "
            "can still read `queued` until the withdrawal is projected."
        )
    )
    message: str | None = None
    error: str | None = None


#: Why inject is refused. One sentence, because it is what `syn control inject`
#: prints and what an operator acts on.
INJECT_NOT_SUPPORTED = (
    "Injecting a message into a running agent is not supported; cancel the "
    "execution and start again with a corrected task (#1530)."
)


class ControlNotSupportedResponse(BaseModel):
    """501: a control the API names but nothing in the system can carry out.

    Shaped as FastAPI's own error body (`detail`), so a client that reads
    errors already reads this one.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    detail: str


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

    # The controller only ever queues a signal; the executor acts on it later,
    # so the state read on admission is not yet the state that results (#1062).
    return ControlResponse(
        success=ctrl.success,
        execution_id=ctrl.execution_id,
        state=ctrl.new_state,
        applied=False,
        message=ctrl.message,
    )


@router.post("/executions/{execution_id}/cancel", response_model=ControlResponse)
async def cancel_execution_endpoint(
    execution_id: str,
    request: CancelRequest | None = None,
) -> ControlResponse:
    """Cancel an execution, or withdraw a start still queued for one (#1650).

    Cancelling a started execution is asynchronous: the signal is queued and the
    executor acts on it later, so the response has `applied: false` and `state`
    is still the pre-cancel state. Re-read `GET /executions/{execution_id}` until
    it reads `cancelled` (#1062). A withdrawn queued start is final at once
    (`applied: true`), though a re-read can still show `queued` until the
    withdrawal is projected.
    """
    reason = request.reason if request else None
    try:
        resolved = await _resolve_execution_id(execution_id)
    except HTTPException as not_found:
        # A rebuild hides queued starts' executions no more than started ones,
        # so a prefix it could not expand is still offered to the withdrawal.
        if not_found.status_code != 404 and not isinstance(not_found, ExecutionReadModelRebuilding):
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
    cancelling it a 404. Its request - or, for a resume, its parent's admitted
    resume - is withdrawn instead: durably, so neither the task waiting for a
    slot nor a restart starts it.
    """
    from syn_api._wiring import get_projection_mgr
    from syn_api.routes.executions.direct_start import withdraw_execution_request
    from syn_api.routes.executions.queued_start import (
        queued_execution_id,
        withdraw_queued_resume,
    )

    full_id = await queued_execution_id(get_projection_mgr(), execution_id)
    if full_id is None:
        return None
    # A direct start's request has its own stream; a resume is withdrawn on the
    # parent that admitted it (#1677). A start is one or the other.
    if not (
        await withdraw_execution_request(full_id, reason)
        or await withdraw_queued_resume(full_id, reason)
    ):
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
        applied=True,
        message="Withdrawn before it started: it will not run",
    )


@router.post(
    "/executions/{execution_id}/inject",
    status_code=501,
    response_model=ControlNotSupportedResponse,
)
async def inject_context_endpoint(
    execution_id: str,
    request: InjectRequest,
) -> ControlNotSupportedResponse:
    """Refused, always: no execution path reads an injected message (#1530).

    It used to answer 200 "Context injection queued" for a message nothing
    would ever deliver, and the queued signal could replace a pending cancel.
    Nothing is resolved or queued now. The route stays so clients keep a
    stable contract and get this answer instead of a 404.
    """
    del execution_id, request
    return ControlNotSupportedResponse(detail=INJECT_NOT_SUPPORTED)


@router.get("/executions/{execution_id}/state", response_model=StateResponse)
async def get_execution_state_endpoint(execution_id: str) -> StateResponse:
    """Get current execution state."""
    try:
        execution_id = await _resolve_execution_id(execution_id)
    except HTTPException:
        raise
    except Exception as exc:
        # Resolution asks the event store first (#1555), so an outage now
        # surfaces here rather than in get_state() below. It is the same
        # failure to answer, and keeps the same 503.
        logger.warning("could not resolve execution %s", execution_id, exc_info=True)
        raise HTTPException(
            status_code=503,
            detail=(
                f"Could not resolve execution {execution_id}: the event store could not "
                f"be read ({type(exc).__name__}). This is not a statement that the "
                "execution is absent."
            ),
        ) from exc
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
