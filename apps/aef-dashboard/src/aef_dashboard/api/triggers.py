"""Trigger management API endpoints.

REST API for managing self-healing trigger rules.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException

from aef_domain.contexts.github._shared.trigger_presets import (
    create_preset_command,
)
from aef_domain.contexts.github.domain.commands.DeleteTriggerCommand import (
    DeleteTriggerCommand,
)
from aef_domain.contexts.github.domain.commands.PauseTriggerCommand import (
    PauseTriggerCommand,
)
from aef_domain.contexts.github.domain.commands.RegisterTriggerCommand import (
    RegisterTriggerCommand,
)
from aef_domain.contexts.github.domain.commands.ResumeTriggerCommand import (
    ResumeTriggerCommand,
)
from aef_domain.contexts.github.domain.queries.get_trigger_history import (
    GetTriggerHistoryQuery,
)
from aef_domain.contexts.github.slices.manage_trigger.ManageTriggerHandler import (
    ManageTriggerHandler,
)
from aef_domain.contexts.github.slices.register_trigger.RegisterTriggerHandler import (
    RegisterTriggerHandler,
)
from aef_domain.contexts.github.slices.register_trigger.trigger_store import (
    get_trigger_store,
)
from aef_domain.contexts.github.slices.trigger_history.handler import (
    GetTriggerHistoryHandler,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/triggers", tags=["triggers"])


@router.post("")
async def register_trigger(body: dict[str, Any]) -> dict[str, Any]:
    """Register a new trigger rule.

    Args:
        body: Trigger configuration including name, event, conditions, etc.

    Returns:
        Created trigger details.
    """
    try:
        conditions = body.get("conditions", [])
        input_mapping = body.get("input_mapping", {})
        config = body.get("config", {})

        cmd = RegisterTriggerCommand(
            name=body["name"],
            event=body["event"],
            conditions=tuple(conditions),
            repository=body.get("repository", ""),
            installation_id=body.get("installation_id", ""),
            workflow_id=body.get("workflow_id", ""),
            input_mapping=tuple(input_mapping.items()) if isinstance(input_mapping, dict) else (),
            config=tuple(config.items()) if isinstance(config, dict) else (),
            created_by=body.get("created_by", "api"),
        )
    except (KeyError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    store = get_trigger_store()
    handler = RegisterTriggerHandler(store=store)
    aggregate = await handler.handle(cmd)

    return {
        "trigger_id": aggregate.trigger_id,
        "name": aggregate.name,
        "status": aggregate.status.value,
    }


@router.get("")
async def list_triggers(
    repository: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    """List all trigger rules.

    Args:
        repository: Filter by repository.
        status: Filter by status.

    Returns:
        List of trigger summaries.
    """
    store = get_trigger_store()
    triggers = await store.list_all(repository=repository, status=status)

    return {
        "triggers": [
            {
                "trigger_id": t.trigger_id,
                "name": t.name,
                "event": t.event,
                "repository": t.repository,
                "workflow_id": t.workflow_id,
                "status": t.status.value,
                "fire_count": t.fire_count,
            }
            for t in triggers
        ],
        "total": len(triggers),
    }


@router.get("/{trigger_id}")
async def get_trigger(trigger_id: str) -> dict[str, Any]:
    """Get trigger details.

    Args:
        trigger_id: The trigger ID.

    Returns:
        Full trigger details.
    """
    store = get_trigger_store()
    trigger = await store.get(trigger_id)

    if trigger is None:
        raise HTTPException(status_code=404, detail=f"Trigger not found: {trigger_id}")

    return {
        "trigger_id": trigger.trigger_id,
        "name": trigger.name,
        "event": trigger.event,
        "conditions": [
            {"field": c.field, "operator": c.operator, "value": c.value} for c in trigger.conditions
        ],
        "repository": trigger.repository,
        "installation_id": trigger.installation_id,
        "workflow_id": trigger.workflow_id,
        "input_mapping": trigger.input_mapping,
        "status": trigger.status.value,
        "fire_count": trigger.fire_count,
        "config": {
            "max_attempts": trigger.config.max_attempts,
            "budget_per_trigger_usd": trigger.config.budget_per_trigger_usd,
            "daily_limit": trigger.config.daily_limit,
            "debounce_seconds": trigger.config.debounce_seconds,
            "cooldown_seconds": trigger.config.cooldown_seconds,
            "skip_if_sender_is_bot": trigger.config.skip_if_sender_is_bot,
        },
        "created_by": trigger.created_by,
    }


@router.patch("/{trigger_id}")
async def update_trigger(trigger_id: str, body: dict[str, Any]) -> dict[str, Any]:
    """Update trigger (pause/resume).

    Args:
        trigger_id: The trigger ID.
        body: Update payload with "action" field (pause/resume).

    Returns:
        Updated trigger status.
    """
    action = body.get("action", "")
    store = get_trigger_store()
    handler = ManageTriggerHandler(store=store)

    if action == "pause":
        event = await handler.pause(
            PauseTriggerCommand(
                trigger_id=trigger_id,
                paused_by=body.get("paused_by", "api"),
                reason=body.get("reason"),
            )
        )
    elif action == "resume":
        event = await handler.resume(
            ResumeTriggerCommand(
                trigger_id=trigger_id,
                resumed_by=body.get("resumed_by", "api"),
            )
        )
    else:
        raise HTTPException(status_code=400, detail=f"Unknown action: {action}")

    if event is None:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot {action} trigger {trigger_id} (invalid state or not found)",
        )

    trigger = await store.get(trigger_id)
    return {
        "trigger_id": trigger_id,
        "status": trigger.status.value if trigger else "unknown",
        "action": action,
    }


@router.delete("/{trigger_id}")
async def delete_trigger(trigger_id: str) -> dict[str, Any]:
    """Delete a trigger rule.

    Args:
        trigger_id: The trigger ID.

    Returns:
        Deletion confirmation.
    """
    store = get_trigger_store()
    handler = ManageTriggerHandler(store=store)
    event = await handler.delete(DeleteTriggerCommand(trigger_id=trigger_id, deleted_by="api"))

    if event is None:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot delete trigger {trigger_id} (not found or already deleted)",
        )

    return {"trigger_id": trigger_id, "status": "deleted"}


@router.post("/presets/{preset_name}")
async def enable_preset(preset_name: str, body: dict[str, Any]) -> dict[str, Any]:
    """Enable a preset for a repository.

    Args:
        preset_name: Name of the preset (self-healing | review-fix).
        body: Must include "repository".

    Returns:
        Created trigger details.
    """
    repository = body.get("repository", "")
    if not repository:
        raise HTTPException(status_code=400, detail="repository is required")

    try:
        cmd = create_preset_command(
            preset_name=preset_name,
            repository=repository,
            installation_id=body.get("installation_id", ""),
            created_by=body.get("created_by", "api"),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    store = get_trigger_store()
    handler = RegisterTriggerHandler(store=store)
    aggregate = await handler.handle(cmd)

    return {
        "trigger_id": aggregate.trigger_id,
        "name": aggregate.name,
        "status": aggregate.status.value,
        "preset": preset_name,
    }


@router.get("/{trigger_id}/history")
async def get_trigger_history(
    trigger_id: str,
    limit: int = 50,
) -> dict[str, Any]:
    """Get execution history for a trigger.

    Args:
        trigger_id: The trigger ID.
        limit: Max entries to return.

    Returns:
        Trigger history entries.
    """
    query = GetTriggerHistoryQuery(trigger_id=trigger_id, limit=limit)
    handler = GetTriggerHistoryHandler()
    entries = handler.handle(query)

    return {
        "trigger_id": trigger_id,
        "entries": [
            {
                "fired_at": e.fired_at.isoformat() if e.fired_at else None,
                "execution_id": e.execution_id,
                "webhook_delivery_id": e.webhook_delivery_id,
                "event_type": e.event_type,
                "pr_number": e.pr_number,
                "status": e.status,
                "cost_usd": e.cost_usd,
            }
            for e in entries
        ],
    }


@router.get("/history")
async def get_all_history(limit: int = 50) -> dict[str, Any]:
    """Get all trigger activity (global).

    Args:
        limit: Max entries to return.

    Returns:
        All trigger history entries.
    """
    from aef_domain.contexts.github.slices.trigger_history.projection import (
        get_trigger_history_projection,
    )

    projection = get_trigger_history_projection()
    entries = projection.get_all_history(limit=limit)

    return {
        "entries": [
            {
                "trigger_id": e.trigger_id,
                "fired_at": e.fired_at.isoformat() if e.fired_at else None,
                "execution_id": e.execution_id,
                "event_type": e.event_type,
                "pr_number": e.pr_number,
                "status": e.status,
            }
            for e in entries
        ],
        "total": len(entries),
    }
