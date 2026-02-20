"""WebSocket endpoint for real-time execution events — thin wrapper over syn_api."""

from __future__ import annotations

import contextlib
from typing import Any

from agentic_logging import get_logger
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

import syn_api.v1.realtime as rt
from syn_api.types import Err

logger = get_logger(__name__)

router = APIRouter(tags=["websocket"])

_ACTIVITY_CHANNEL = "_activity_"


@router.websocket("/ws/executions/{execution_id}")
async def execution_websocket(websocket: WebSocket, execution_id: str) -> None:
    """WebSocket endpoint for real-time execution events."""
    await websocket.accept()
    realtime = rt.get_realtime_projection_ref()

    # Register for real-time events
    await realtime.connect(execution_id, websocket)

    try:
        # Send connection confirmation
        await websocket.send_json(
            {
                "type": "connected",
                "execution_id": execution_id,
                "message": "Subscribed to execution events",
            }
        )

        logger.info(
            "WebSocket connected for execution",
            extra={"execution_id": execution_id},
        )

        # Keep connection alive
        while True:
            try:
                data = await websocket.receive_json()
                logger.debug(
                    "Received WebSocket message",
                    extra={"execution_id": execution_id, "data": data},
                )
            except WebSocketDisconnect:
                logger.info(
                    "WebSocket client disconnected",
                    extra={"execution_id": execution_id},
                )
                break
            except Exception as e:
                logger.warning(
                    "WebSocket receive error, closing connection",
                    extra={"execution_id": execution_id, "error": str(e)},
                )
                break

    except WebSocketDisconnect:
        logger.debug(
            "WebSocket disconnected during send",
            extra={"execution_id": execution_id},
        )
    except Exception as e:
        logger.exception(
            "WebSocket error",
            extra={"execution_id": execution_id, "error": str(e)},
        )
        with contextlib.suppress(Exception):
            await websocket.send_json({"type": "error", "error": str(e)})
    finally:
        logger.debug(
            "Cleaning up WebSocket connection",
            extra={"execution_id": execution_id},
        )
        await realtime.disconnect(execution_id, websocket)


@router.websocket("/ws/activity")
async def activity_websocket(websocket: WebSocket) -> None:
    """WebSocket endpoint for the global activity feed.

    Receives repo-level events (git commits, pushes, etc.) that are not
    scoped to a specific execution. Used by the dashboard home EventFeed.
    """
    await websocket.accept()
    realtime = rt.get_realtime_projection_ref()

    await realtime.connect(_ACTIVITY_CHANNEL, websocket)

    try:
        await websocket.send_json(
            {"type": "connected", "channel": "activity", "message": "Subscribed to activity feed"}
        )

        while True:
            try:
                await websocket.receive_json()
            except WebSocketDisconnect:
                break
            except Exception:
                break

    except WebSocketDisconnect:
        pass
    except Exception as e:
        with contextlib.suppress(Exception):
            await websocket.send_json({"type": "error", "error": str(e)})
    finally:
        await realtime.disconnect(_ACTIVITY_CHANNEL, websocket)


@router.get("/ws/health")
async def websocket_health() -> dict[str, Any]:
    """Health check for WebSocket subsystem."""
    result = await rt.get_realtime_health()

    if isinstance(result, Err):
        return {"status": "unhealthy"}

    health = result.value
    return {
        "status": "healthy",
        "active_executions": health.active_executions,
        "active_connections": health.active_connections,
    }
