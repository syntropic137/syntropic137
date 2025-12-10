"""WebSocket endpoint for real-time execution events.

This endpoint provides bidirectional communication for:
- Server → Client: Domain events from RealTimeProjection
- Client → Server: (Future) Control commands (pause/resume/cancel)

Events flow through proper event sourcing:
    Event Store → Subscription Service → ProjectionManager → RealTimeProjection → WebSocket → UI

This is the correct ES pattern - no parallel event paths.
"""

from __future__ import annotations

import contextlib
import logging
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from aef_adapters.projections import get_realtime_projection

logger = logging.getLogger(__name__)

router = APIRouter(tags=["websocket"])


@router.websocket("/ws/executions/{execution_id}")
async def execution_websocket(websocket: WebSocket, execution_id: str) -> None:
    """WebSocket endpoint for real-time execution events.

    This endpoint:
    1. Accepts WebSocket connection
    2. Registers with RealTimeProjection for events
    3. Sends initial state to client
    4. Keeps connection open for real-time event push

    Messages to client (from RealTimeProjection):
        {"type": "event", "event_type": "PhaseStarted", "data": {...}, "timestamp": "..."}
        {"type": "event", "event_type": "OperationRecorded", "data": {...}, "timestamp": "..."}
        {"type": "event", "event_type": "WorkflowCompleted", "data": {...}, "timestamp": "..."}

    Messages to client (connection management):
        {"type": "connected", "execution_id": "...", "message": "..."}
        {"type": "error", "error": "..."}

    Messages from client (future - control commands):
        {"command": "pause", "reason": "..."}
        {"command": "resume"}
        {"command": "cancel", "reason": "..."}

    Args:
        websocket: The WebSocket connection.
        execution_id: The execution to subscribe to.
    """
    await websocket.accept()
    realtime = get_realtime_projection()

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

        # Keep connection alive and handle incoming messages
        # (Future: parse control commands here)
        while True:
            try:
                data = await websocket.receive_json()
                # Future: Handle control commands
                # command = data.get("command")
                # if command == "pause": ...
                logger.debug(
                    "Received WebSocket message",
                    extra={"execution_id": execution_id, "data": data},
                )
            except Exception as e:
                # JSON parse error or other issue
                logger.debug(
                    "Error processing WebSocket message",
                    extra={"execution_id": execution_id, "error": str(e)},
                )

    except WebSocketDisconnect:
        logger.info(
            "WebSocket disconnected",
            extra={"execution_id": execution_id},
        )
    except Exception as e:
        logger.exception(
            "WebSocket error",
            extra={"execution_id": execution_id, "error": str(e)},
        )
        with contextlib.suppress(Exception):
            await websocket.send_json(
                {
                    "type": "error",
                    "error": str(e),
                }
            )
    finally:
        # Always unregister on disconnect
        await realtime.disconnect(execution_id, websocket)


@router.get("/ws/health")
async def websocket_health() -> dict[str, Any]:
    """Health check for WebSocket subsystem.

    Returns connection statistics from RealTimeProjection.
    """
    realtime = get_realtime_projection()
    return {
        "status": "healthy",
        "active_executions": realtime.execution_count,
        "active_connections": realtime.connection_count,
    }
