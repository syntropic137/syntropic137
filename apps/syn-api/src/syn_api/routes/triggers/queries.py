"""Trigger query operations and read endpoints."""

from __future__ import annotations

import dataclasses
import logging
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, HTTPException

from syn_api._wiring import ensure_connected, get_trigger_store
from syn_api.types import (
    Err,
    Ok,
    Result,
    TriggerDetail,
    TriggerError,
    TriggerHistoryEntry,
    TriggerSummary,
)

if TYPE_CHECKING:
    from syn_api.auth import AuthContext

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/triggers", tags=["triggers"])


# ---------------------------------------------------------------------------
# Service functions (importable by tests)
# ---------------------------------------------------------------------------


async def list_triggers(
    repository: str | None = None,
    status: str | None = None,
    auth: AuthContext | None = None,  # noqa: ARG001
) -> Result[list[TriggerSummary], TriggerError]:
    """List trigger rules with optional filters."""
    await ensure_connected()
    store = get_trigger_store()

    try:
        triggers = await store.list_all(repository=repository, status=status)
    except Exception as e:
        return Err(TriggerError.INVALID_INPUT, message=str(e))

    return Ok(
        [
            TriggerSummary(
                trigger_id=t.trigger_id,
                name=t.name,
                event=t.event,
                repository=t.repository,
                workflow_id=t.workflow_id,
                status=t.status,
                fire_count=t.fire_count,
                created_at=t.created_at if hasattr(t, "created_at") else None,
            )
            for t in triggers
        ]
    )


def _resolve_config(config: Any) -> dict[str, Any]:
    """Convert a config value (dataclass, dict, or other) to a plain dict."""
    if dataclasses.is_dataclass(config) and not isinstance(config, type):
        return dataclasses.asdict(config)  # type: ignore[arg-type]  # guarded by is_dataclass
    if isinstance(config, dict):
        return dict(config)
    return {}


async def get_trigger(
    trigger_id: str,
    auth: AuthContext | None = None,  # noqa: ARG001
) -> Result[TriggerDetail, TriggerError]:
    """Get detailed information about a trigger rule."""
    await ensure_connected()
    store = get_trigger_store()
    indexed = await store.get(trigger_id)

    if indexed is None:
        return Err(TriggerError.NOT_FOUND, message=f"Trigger {trigger_id} not found")

    return Ok(
        TriggerDetail(
            trigger_id=indexed.trigger_id,
            name=indexed.name,
            event=indexed.event,
            repository=indexed.repository,
            workflow_id=indexed.workflow_id,
            status=indexed.status,
            fire_count=indexed.fire_count,
            created_at=indexed.created_at if hasattr(indexed, "created_at") else None,
            conditions=list(indexed.conditions) if indexed.conditions else [],
            input_mapping=dict(indexed.input_mapping) if indexed.input_mapping else {},
            config=_resolve_config(indexed.config),
            installation_id=indexed.installation_id or "",
            created_by=indexed.created_by or "",
            last_fired_at=indexed.last_fired_at if hasattr(indexed, "last_fired_at") else None,
        )
    )


async def get_trigger_history(
    trigger_id: str,
    limit: int = 50,
    auth: AuthContext | None = None,  # noqa: ARG001
) -> Result[list[TriggerHistoryEntry], TriggerError]:
    """Get execution history for a trigger rule."""
    from syn_domain.contexts.github.domain.queries.get_trigger_history import GetTriggerHistoryQuery
    from syn_domain.contexts.github.slices.trigger_history.GetTriggerHistoryHandler import (
        get_trigger_history_handler,
    )

    try:
        query = GetTriggerHistoryQuery(trigger_id=trigger_id, limit=limit)
    except ValueError as e:
        return Err(TriggerError.INVALID_INPUT, message=str(e))

    handler = get_trigger_history_handler()
    entries = await handler.handle(query)

    return Ok(
        [
            TriggerHistoryEntry(
                trigger_id=e.trigger_id,
                execution_id=e.execution_id,
                webhook_delivery_id=e.webhook_delivery_id,
                github_event_type=e.github_event_type,
                repository=e.repository,
                pr_number=e.pr_number,
                fired_at=e.fired_at,
                status=e.status,
                cost_usd=e.cost_usd,
            )
            for e in entries
        ]
    )


# ---------------------------------------------------------------------------
# HTTP Endpoints
# ---------------------------------------------------------------------------


@router.get("")
async def list_triggers_endpoint(
    repository: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    """List all trigger rules."""
    result = await list_triggers(repository=repository, status=status)
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


async def _collect_history_entries(
    triggers: list[TriggerSummary], limit: int
) -> list[dict[str, Any]]:
    """Collect history entries across all triggers."""
    all_entries: list[dict[str, Any]] = []
    for t in triggers:
        hist = await get_trigger_history(trigger_id=t.trigger_id, limit=limit)
        if isinstance(hist, Err):
            continue
        all_entries.extend(
            {
                "trigger_id": t.trigger_id,
                "fired_at": e.fired_at.isoformat() if e.fired_at else None,
                "execution_id": e.execution_id,
                "event_type": e.github_event_type,
                "pr_number": e.pr_number,
                "status": e.status,
            }
            for e in hist.value
        )
    return all_entries


@router.get("/history")
async def get_all_history_endpoint(limit: int = 50) -> dict[str, Any]:
    """Get all trigger activity (global)."""
    list_result = await list_triggers()
    if isinstance(list_result, Err):
        return {"entries": [], "total": 0}

    all_entries = await _collect_history_entries(list_result.value, limit)
    all_entries.sort(key=lambda x: x.get("fired_at") or "", reverse=True)
    all_entries = all_entries[:limit]
    return {"entries": all_entries, "total": len(all_entries)}


@router.get("/{trigger_id}")
async def get_trigger_endpoint(trigger_id: str) -> dict[str, Any]:
    """Get trigger details."""
    result = await get_trigger(trigger_id)
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


@router.get("/{trigger_id}/history")
async def get_trigger_history_endpoint(
    trigger_id: str,
    limit: int = 50,
) -> dict[str, Any]:
    """Get execution history for a trigger."""
    result = await get_trigger_history(trigger_id=trigger_id, limit=limit)
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
