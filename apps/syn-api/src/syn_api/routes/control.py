"""WebSocket and HTTP control endpoints — thin wrapper over v1."""

from __future__ import annotations

import logging
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

import syn_api.v1.executions as ex
from syn_api.types import Err

logger = logging.getLogger(__name__)
router = APIRouter(tags=["control"])


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


# =============================================================================
# WebSocket Endpoint
# =============================================================================


@router.websocket("/ws/control/{execution_id}")
async def control_websocket(websocket: WebSocket, execution_id: str) -> None:
    """WebSocket endpoint for bidirectional execution control."""
    await websocket.accept()

    try:
        state_result = await ex.get_state(execution_id)
        state_val = "unknown"
        if not isinstance(state_result, Err):
            state_val = state_result.value.get("state", "unknown")

        await websocket.send_json(
            {"type": "state", "execution_id": execution_id, "state": state_val}
        )

        while True:
            data = await websocket.receive_json()
            cmd_type = data.get("command")

            result = None
            if cmd_type == "pause":
                result = await ex.pause(execution_id, reason=data.get("reason"))
            elif cmd_type == "resume":
                result = await ex.resume(execution_id)
            elif cmd_type == "cancel":
                result = await ex.cancel(execution_id, reason=data.get("reason"))
            elif cmd_type == "inject":
                result = await ex.inject(
                    execution_id,
                    message=data.get("message", ""),
                    role=data.get("role", "user"),
                )

            if result is not None and not isinstance(result, Err):
                ctrl = result.value
                await websocket.send_json(
                    {
                        "type": "result",
                        "success": ctrl.success,
                        "state": ctrl.new_state,
                        "message": ctrl.message,
                        "error": ctrl.error,
                    }
                )
            elif result is not None:
                await websocket.send_json({"type": "error", "error": result.message})
            else:
                await websocket.send_json(
                    {"type": "error", "error": f"Unknown command: {cmd_type}"}
                )

    except WebSocketDisconnect:
        logger.debug("WebSocket disconnected", extra={"execution_id": execution_id})
    except Exception as e:
        logger.exception("WebSocket error")
        await websocket.close(code=1011, reason=str(e))


# =============================================================================
# HTTP Endpoints
# =============================================================================


async def _handle_control_result(result: Any, _action: str = "") -> ControlResponse:
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
async def pause_execution(
    execution_id: str,
    request: PauseRequest | None = None,
) -> ControlResponse:
    """Pause a running execution."""
    result = await ex.pause(execution_id, reason=request.reason if request else None)
    return await _handle_control_result(result, "pause")


@router.post("/executions/{execution_id}/resume", response_model=ControlResponse)
async def resume_execution(execution_id: str) -> ControlResponse:
    """Resume a paused execution."""
    result = await ex.resume(execution_id)
    return await _handle_control_result(result, "resume")


@router.post("/executions/{execution_id}/cancel", response_model=ControlResponse)
async def cancel_execution(
    execution_id: str,
    request: CancelRequest | None = None,
) -> ControlResponse:
    """Cancel a running or paused execution."""
    result = await ex.cancel(execution_id, reason=request.reason if request else None)
    return await _handle_control_result(result, "cancel")


@router.post("/executions/{execution_id}/inject", response_model=ControlResponse)
async def inject_context(
    execution_id: str,
    request: InjectRequest,
) -> ControlResponse:
    """Inject a message into the execution context."""
    result = await ex.inject(execution_id, message=request.message, role=request.role)
    return await _handle_control_result(result, "inject")


@router.get("/executions/{execution_id}/state", response_model=StateResponse)
async def get_execution_state(execution_id: str) -> StateResponse:
    """Get current execution state."""
    result = await ex.get_state(execution_id)

    state_val = "unknown"
    if not isinstance(result, Err):
        state_val = result.value.get("state", "unknown")

    return StateResponse(execution_id=execution_id, state=state_val)
