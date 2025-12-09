"""WebSocket and HTTP control endpoints for real-time execution control."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from aef_adapters.control import (
    CancelExecution,
    ControlCommand,
    InjectContext,
    PauseExecution,
    ResumeExecution,
)
from aef_dashboard.services.control import get_controller

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
    role: str = "user"


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
    """WebSocket endpoint for bidirectional execution control.

    Messages from client:
        {"command": "pause", "reason": "..."}
        {"command": "resume"}
        {"command": "cancel", "reason": "..."}
        {"command": "inject", "message": "...", "role": "user"}

    Messages to client:
        {"type": "state", "execution_id": "...", "state": "running|paused|..."}
        {"type": "result", "success": true, "state": "...", "message": "..."}
        {"type": "error", "error": "..."}
    """
    await websocket.accept()
    controller = get_controller()

    try:
        # Send initial state
        state = await controller.get_state(execution_id)
        await websocket.send_json(
            {
                "type": "state",
                "execution_id": execution_id,
                "state": state.value if state else "unknown",
            }
        )

        # Handle incoming commands
        while True:
            data = await websocket.receive_json()
            command = _parse_command(execution_id, data)

            if command:
                result = await controller.handle_command(command)
                await websocket.send_json(
                    {
                        "type": "result",
                        "success": result.success,
                        "state": result.new_state,
                        "message": result.message,
                        "error": result.error,
                    }
                )
            else:
                await websocket.send_json(
                    {
                        "type": "error",
                        "error": f"Unknown command: {data.get('command')}",
                    }
                )

    except WebSocketDisconnect:
        logger.debug("WebSocket disconnected", extra={"execution_id": execution_id})
    except Exception as e:
        logger.exception("WebSocket error")
        await websocket.close(code=1011, reason=str(e))


def _parse_command(execution_id: str, data: dict[str, Any]) -> ControlCommand | None:
    """Parse WebSocket message into command."""
    cmd_type = data.get("command")

    if cmd_type == "pause":
        return PauseExecution(execution_id=execution_id, reason=data.get("reason"))
    elif cmd_type == "resume":
        return ResumeExecution(execution_id=execution_id)
    elif cmd_type == "cancel":
        return CancelExecution(execution_id=execution_id, reason=data.get("reason"))
    elif cmd_type == "inject":
        return InjectContext(
            execution_id=execution_id,
            message=data.get("message", ""),
            role=data.get("role", "user"),
        )
    return None


# =============================================================================
# HTTP Endpoints
# =============================================================================


@router.post(
    "/executions/{execution_id}/pause",
    response_model=ControlResponse,
    summary="Pause execution",
    description="Send a pause signal to a running execution. "
    "The execution will pause at the next yield point.",
)
async def pause_execution(
    execution_id: str,
    request: PauseRequest | None = None,
) -> ControlResponse:
    """Pause a running execution."""
    controller = get_controller()
    cmd = PauseExecution(
        execution_id=execution_id,
        reason=request.reason if request else None,
    )
    result = await controller.handle_command(cmd)

    if not result.success:
        raise HTTPException(status_code=400, detail=result.error)

    return ControlResponse(
        success=result.success,
        execution_id=result.execution_id,
        state=result.new_state,
        message=result.message,
    )


@router.post(
    "/executions/{execution_id}/resume",
    response_model=ControlResponse,
    summary="Resume execution",
    description="Send a resume signal to a paused execution.",
)
async def resume_execution(execution_id: str) -> ControlResponse:
    """Resume a paused execution."""
    controller = get_controller()
    cmd = ResumeExecution(execution_id=execution_id)
    result = await controller.handle_command(cmd)

    if not result.success:
        raise HTTPException(status_code=400, detail=result.error)

    return ControlResponse(
        success=result.success,
        execution_id=result.execution_id,
        state=result.new_state,
        message=result.message,
    )


@router.post(
    "/executions/{execution_id}/cancel",
    response_model=ControlResponse,
    summary="Cancel execution",
    description="Send a cancel signal to a running or paused execution. "
    "The execution will terminate with cleanup.",
)
async def cancel_execution(
    execution_id: str,
    request: CancelRequest | None = None,
) -> ControlResponse:
    """Cancel a running or paused execution."""
    controller = get_controller()
    cmd = CancelExecution(
        execution_id=execution_id,
        reason=request.reason if request else None,
    )
    result = await controller.handle_command(cmd)

    if not result.success:
        raise HTTPException(status_code=400, detail=result.error)

    return ControlResponse(
        success=result.success,
        execution_id=result.execution_id,
        state=result.new_state,
        message=result.message,
    )


@router.post(
    "/executions/{execution_id}/inject",
    response_model=ControlResponse,
    summary="Inject context",
    description="Inject a message into the agent's context. "
    "Useful for providing additional guidance during execution.",
)
async def inject_context(
    execution_id: str,
    request: InjectRequest,
) -> ControlResponse:
    """Inject a message into the execution context."""
    controller = get_controller()
    cmd = InjectContext(
        execution_id=execution_id,
        message=request.message,
        role=request.role,  # type: ignore[arg-type]
    )
    result = await controller.handle_command(cmd)

    if not result.success:
        raise HTTPException(status_code=400, detail=result.error)

    return ControlResponse(
        success=result.success,
        execution_id=result.execution_id,
        state=result.new_state,
        message=result.message,
    )


@router.get(
    "/executions/{execution_id}/state",
    response_model=StateResponse,
    summary="Get execution state",
    description="Get the current control state of an execution.",
)
async def get_execution_state(execution_id: str) -> StateResponse:
    """Get current execution state."""
    controller = get_controller()
    state = await controller.get_state(execution_id)

    return StateResponse(
        execution_id=execution_id,
        state=state.value if state else "unknown",
    )
