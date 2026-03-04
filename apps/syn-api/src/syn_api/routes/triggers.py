"""Trigger management API endpoints — thin wrapper over v1."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException

import syn_api.v1.triggers as trig
from syn_api.types import Err

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/triggers", tags=["triggers"])


@router.post("")
async def register_trigger(body: dict[str, Any]) -> dict[str, Any]:
    """Register a new trigger rule."""
    try:
        result = await trig.register_trigger(
            name=body["name"],
            event=body["event"],
            repository=body.get("repository", ""),
            workflow_id=body.get("workflow_id", ""),
            conditions=body.get("conditions"),
            installation_id=body.get("installation_id", ""),
            input_mapping=body.get("input_mapping"),
            config=body.get("config"),
            created_by=body.get("created_by", "api"),
        )
    except (KeyError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    if isinstance(result, Err):
        raise HTTPException(status_code=400, detail=result.message)

    return {"trigger_id": result.value, "name": body["name"], "status": "active"}


@router.get("")
async def list_triggers(
    repository: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    """List all trigger rules."""
    result = await trig.list_triggers(repository=repository, status=status)

    if isinstance(result, Err):
        raise HTTPException(status_code=500, detail=result.message)

    return {
        "triggers": [
            {
                "trigger_id": t.trigger_id,
                "name": t.name,
                "event": t.event,
                "repository": t.repository,
                "workflow_id": t.workflow_id,
                "status": str(t.status),
                "fire_count": t.fire_count,
            }
            for t in result.value
        ],
        "total": len(result.value),
    }


@router.get("/{trigger_id}")
async def get_trigger(trigger_id: str) -> dict[str, Any]:
    """Get trigger details."""
    result = await trig.get_trigger(trigger_id)

    if isinstance(result, Err):
        raise HTTPException(status_code=404, detail=f"Trigger not found: {trigger_id}")

    t = result.value
    return {
        "trigger_id": t.trigger_id,
        "name": t.name,
        "event": t.event,
        "conditions": t.conditions,
        "repository": t.repository,
        "installation_id": t.installation_id,
        "workflow_id": t.workflow_id,
        "input_mapping": t.input_mapping,
        "status": str(t.status),
        "fire_count": t.fire_count,
        "config": t.config,
        "created_by": t.created_by,
    }


@router.patch("/{trigger_id}")
async def update_trigger(trigger_id: str, body: dict[str, Any]) -> dict[str, Any]:
    """Update trigger (pause/resume)."""
    action = body.get("action", "")

    if action == "pause":
        result = await trig.pause_trigger(
            trigger_id=trigger_id,
            reason=body.get("reason"),
            paused_by=body.get("paused_by", "api"),
        )
    elif action == "resume":
        result = await trig.resume_trigger(
            trigger_id=trigger_id,
            resumed_by=body.get("resumed_by", "api"),
        )
    else:
        raise HTTPException(status_code=400, detail=f"Unknown action: {action}")

    if isinstance(result, Err):
        raise HTTPException(
            status_code=409,
            detail=f"Cannot {action} trigger {trigger_id}: {result.message}",
        )

    return {"trigger_id": trigger_id, "status": action + "d", "action": action}


@router.delete("/{trigger_id}")
async def delete_trigger(trigger_id: str) -> dict[str, Any]:
    """Delete a trigger rule."""
    result = await trig.delete_trigger(trigger_id=trigger_id, deleted_by="api")

    if isinstance(result, Err):
        raise HTTPException(
            status_code=409,
            detail=f"Cannot delete trigger {trigger_id}: {result.message}",
        )

    return {"trigger_id": trigger_id, "status": "deleted"}


@router.post("/presets/{preset_name}")
async def enable_preset(preset_name: str, body: dict[str, Any]) -> dict[str, Any]:
    """Enable a preset for a repository."""
    repository = body.get("repository", "")
    if not repository:
        raise HTTPException(status_code=400, detail="repository is required")

    result = await trig.enable_preset(
        preset_name=preset_name,
        repository=repository,
        installation_id=body.get("installation_id", ""),
        created_by=body.get("created_by", "api"),
    )

    if isinstance(result, Err):
        raise HTTPException(status_code=400, detail=result.message)

    return {
        "trigger_id": result.value,
        "name": preset_name,
        "status": "active",
        "preset": preset_name,
    }


@router.get("/{trigger_id}/history")
async def get_trigger_history(
    trigger_id: str,
    limit: int = 50,
) -> dict[str, Any]:
    """Get execution history for a trigger."""
    result = trig.get_trigger_history(trigger_id=trigger_id, limit=limit)

    if isinstance(result, Err):
        raise HTTPException(status_code=404, detail=result.message)

    return {
        "trigger_id": trigger_id,
        "entries": [
            {
                "fired_at": e.fired_at.isoformat() if e.fired_at else None,
                "execution_id": e.execution_id,
                "webhook_delivery_id": e.webhook_delivery_id,
                "event_type": e.github_event_type,
                "pr_number": e.pr_number,
                "status": e.status,
                "cost_usd": e.cost_usd,
            }
            for e in result.value
        ],
    }


@router.get("/history")
async def get_all_history(limit: int = 50) -> dict[str, Any]:
    """Get all trigger activity (global)."""
    list_result = await trig.list_triggers()
    if isinstance(list_result, Err):
        return {"entries": [], "total": 0}

    all_entries = []
    for t in list_result.value:
        hist = trig.get_trigger_history(trigger_id=t.trigger_id, limit=limit)
        if not isinstance(hist, Err):
            for e in hist.value:
                all_entries.append(
                    {
                        "trigger_id": t.trigger_id,
                        "fired_at": e.fired_at.isoformat() if e.fired_at else None,
                        "execution_id": e.execution_id,
                        "event_type": e.github_event_type,
                        "pr_number": e.pr_number,
                        "status": e.status,
                    }
                )

    all_entries.sort(key=lambda x: x.get("fired_at") or "", reverse=True)
    all_entries = all_entries[:limit]

    return {"entries": all_entries, "total": len(all_entries)}
