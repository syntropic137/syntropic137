"""Trigger command operations and write endpoints."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, HTTPException

from syn_api._wiring import (
    ensure_connected,
    get_trigger_repo,
    get_trigger_store,
    get_workflow_repo,
    sync_published_events_to_projections,
)
from syn_api.types import (
    EnablePresetRequest,
    Err,
    Ok,
    RegisterTriggerRequest,
    Result,
    TriggerActionResponse,
    TriggerDetail,
    TriggerError,
    UpdateTriggerRequest,
)
from syn_domain.contexts.github.domain.aggregate_trigger.TriggerStatus import TriggerStatus

if TYPE_CHECKING:
    from syn_api.auth import AuthContext

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/triggers", tags=["triggers"])


async def _resolve_installation_id(installation_id: str, repository: str) -> str:
    """Auto-resolve installation_id from the GitHub App if not provided."""
    if installation_id or not repository:
        return installation_id
    try:
        from syn_adapters.github.client import get_github_client

        client = get_github_client()
        resolved = await client.get_installation_for_repo(repository)
        logger.info("Auto-resolved installation_id=%s for %s", resolved, repository)
        return str(resolved)
    except Exception:
        logger.warning(
            "Could not auto-resolve installation_id for %s",
            repository,
            exc_info=True,
        )
        return installation_id


async def register_trigger(
    name: str,
    event: str,
    repository: str,
    workflow_id: str,
    conditions: list[dict] | None = None,
    installation_id: str = "",
    input_mapping: dict[str, str] | None = None,
    config: dict | None = None,
    created_by: str = "",
    auth: AuthContext | None = None,  # noqa: ARG001
) -> Result[str, TriggerError]:
    """Register a new GitHub event trigger for a workflow."""
    from syn_domain.contexts.github.domain.commands.RegisterTriggerCommand import (
        RegisterTriggerCommand,
    )
    from syn_domain.contexts.github.slices.register_trigger.RegisterTriggerHandler import (
        RegisterTriggerHandler,
    )

    await ensure_connected()
    installation_id = await _resolve_installation_id(installation_id, repository)

    workflow_repo = get_workflow_repo()
    if not await workflow_repo.exists(workflow_id):
        return Err(
            TriggerError.WORKFLOW_NOT_FOUND,
            message=f"Workflow '{workflow_id}' does not exist. Seed workflows before creating triggers.",
        )

    try:
        command = RegisterTriggerCommand(
            name=name,
            event=event,
            repository=repository,
            workflow_id=workflow_id,
            conditions=tuple(conditions or []),
            installation_id=installation_id,
            input_mapping=tuple((input_mapping or {}).items()),
            config=tuple((config or {}).items()),
            created_by=created_by,
        )
    except ValueError as e:
        return Err(TriggerError.INVALID_INPUT, message=str(e))

    store = get_trigger_store()
    repo = get_trigger_repo()
    handler = RegisterTriggerHandler(store=store, repository=repo)

    try:
        aggregate = await handler.handle(command)
        await _index_and_sync_trigger(store, aggregate)
        return Ok(aggregate.trigger_id)
    except Exception as e:
        return Err(TriggerError.INVALID_INPUT, message=str(e))


async def _index_and_sync_trigger(store: Any, aggregate: Any) -> None:  # noqa: ANN401
    """Index a trigger aggregate in the store and sync projections."""
    await store.index_trigger(
        trigger_id=aggregate.trigger_id,
        name=aggregate.name,
        event=aggregate.event,
        repository=aggregate.repository,
        workflow_id=aggregate.workflow_id,
        conditions=[
            {"field": c.field, "operator": c.operator, "value": c.value}
            for c in aggregate.conditions
        ],
        input_mapping=aggregate.input_mapping,
        config=aggregate.config,
        installation_id=aggregate.installation_id,
        created_by=aggregate.created_by,
        status=aggregate.status.value,
        created_at=datetime.now(UTC),
    )
    await sync_published_events_to_projections()


async def _check_preset_duplicate(
    repository: str, command_name: str, command_event: str
) -> Result[None, TriggerError]:
    """Check if a trigger with the same name+event already exists for the repo."""
    from syn_api.routes.triggers.queries import list_triggers

    existing = await list_triggers(repository=repository)
    if not isinstance(existing, Ok):
        return Ok(None)

    for t in existing.value:
        if (
            t.name == command_name
            and t.event == command_event
            and t.status != TriggerStatus.DELETED
        ):
            return Err(
                TriggerError.INVALID_INPUT,
                message=f"Trigger '{command_name}' already exists for {repository}",
            )
    return Ok(None)


async def enable_preset(
    preset_name: str,
    repository: str,
    installation_id: str = "",
    created_by: str = "system",
    workflow_id: str = "",
    auth: AuthContext | None = None,  # noqa: ARG001
) -> Result[str, TriggerError]:
    """Enable a built-in trigger preset for a repository."""
    from syn_domain.contexts.github._shared.trigger_presets import create_preset_command
    from syn_domain.contexts.github.slices.register_trigger.RegisterTriggerHandler import (
        RegisterTriggerHandler,
    )

    await ensure_connected()
    installation_id = await _resolve_installation_id(installation_id, repository)

    try:
        command = create_preset_command(
            preset_name=preset_name,
            repository=repository,
            installation_id=installation_id,
            created_by=created_by,
            workflow_id=workflow_id,
        )
    except (ValueError, KeyError):
        return Err(TriggerError.PRESET_NOT_FOUND, message=f"Preset '{preset_name}' not found")

    workflow_repo = get_workflow_repo()
    if not await workflow_repo.exists(command.workflow_id):
        return Err(
            TriggerError.WORKFLOW_NOT_FOUND,
            message=f"Workflow '{command.workflow_id}' does not exist. Seed workflows before creating triggers.",
        )

    dedup = await _check_preset_duplicate(repository, command.name, command.event)
    if isinstance(dedup, Err):
        return dedup

    store = get_trigger_store()
    repo = get_trigger_repo()
    handler = RegisterTriggerHandler(store=store, repository=repo)

    try:
        aggregate = await handler.handle(command)
        await _index_and_sync_trigger(store, aggregate)
        return Ok(aggregate.trigger_id)
    except Exception as e:
        return Err(TriggerError.INVALID_INPUT, message=str(e))


async def pause_trigger(
    trigger_id: str,
    reason: str | None = None,
    paused_by: str = "",
    auth: AuthContext | None = None,  # noqa: ARG001
) -> Result[None, TriggerError]:
    """Pause an active trigger."""
    from syn_domain.contexts.github.domain.commands.PauseTriggerCommand import PauseTriggerCommand
    from syn_domain.contexts.github.slices.manage_trigger.ManageTriggerHandler import (
        ManageTriggerHandler,
    )

    await ensure_connected()
    store = get_trigger_store()

    indexed = await store.get(trigger_id)
    if indexed is None:
        return Err(TriggerError.NOT_FOUND, message=f"Trigger {trigger_id} not found")
    if indexed.status == TriggerStatus.PAUSED:
        return Err(TriggerError.ALREADY_PAUSED, message="Trigger is already paused")
    if indexed.status == TriggerStatus.DELETED:
        return Err(TriggerError.ALREADY_DELETED, message="Trigger has been deleted")

    command = PauseTriggerCommand(trigger_id=trigger_id, paused_by=paused_by, reason=reason)
    repo = get_trigger_repo()
    handler = ManageTriggerHandler(store=store, repository=repo)
    result = await handler.pause(command)

    if result is None:
        return Err(TriggerError.NOT_FOUND, message=f"Failed to pause trigger {trigger_id}")

    await store.update_status(trigger_id, TriggerStatus.PAUSED.value)
    await sync_published_events_to_projections()
    return Ok(None)


async def resume_trigger(
    trigger_id: str,
    resumed_by: str = "",
    auth: AuthContext | None = None,  # noqa: ARG001
) -> Result[None, TriggerError]:
    """Resume a paused trigger."""
    from syn_domain.contexts.github.domain.commands.ResumeTriggerCommand import ResumeTriggerCommand
    from syn_domain.contexts.github.slices.manage_trigger.ManageTriggerHandler import (
        ManageTriggerHandler,
    )

    await ensure_connected()
    store = get_trigger_store()

    indexed = await store.get(trigger_id)
    if indexed is None:
        return Err(TriggerError.NOT_FOUND, message=f"Trigger {trigger_id} not found")
    if indexed.status == TriggerStatus.ACTIVE:
        return Err(TriggerError.ALREADY_ACTIVE, message="Trigger is not paused")
    if indexed.status == TriggerStatus.DELETED:
        return Err(TriggerError.ALREADY_DELETED, message="Trigger has been deleted")

    command = ResumeTriggerCommand(trigger_id=trigger_id, resumed_by=resumed_by)
    repo = get_trigger_repo()
    handler = ManageTriggerHandler(store=store, repository=repo)
    result = await handler.resume(command)

    if result is None:
        return Err(TriggerError.NOT_FOUND, message=f"Failed to resume trigger {trigger_id}")

    await store.update_status(trigger_id, TriggerStatus.ACTIVE.value)
    await sync_published_events_to_projections()
    return Ok(None)


async def delete_trigger(
    trigger_id: str,
    deleted_by: str = "",
    auth: AuthContext | None = None,  # noqa: ARG001
) -> Result[None, TriggerError]:
    """Soft-delete a trigger rule."""
    from syn_domain.contexts.github.domain.commands.DeleteTriggerCommand import DeleteTriggerCommand
    from syn_domain.contexts.github.slices.manage_trigger.ManageTriggerHandler import (
        ManageTriggerHandler,
    )

    await ensure_connected()
    store = get_trigger_store()

    indexed = await store.get(trigger_id)
    if indexed is None:
        return Err(TriggerError.NOT_FOUND, message=f"Trigger {trigger_id} not found")
    if indexed.status == TriggerStatus.DELETED:
        return Err(TriggerError.ALREADY_DELETED, message="Trigger has already been deleted")

    command = DeleteTriggerCommand(trigger_id=trigger_id, deleted_by=deleted_by)
    repo = get_trigger_repo()
    handler = ManageTriggerHandler(store=store, repository=repo)
    result = await handler.delete(command)

    if result is None:
        return Err(TriggerError.NOT_FOUND, message=f"Failed to delete trigger {trigger_id}")

    await store.update_status(trigger_id, TriggerStatus.DELETED.value)
    await sync_published_events_to_projections()
    return Ok(None)


async def disable_triggers(
    repository: str,
    paused_by: str = "",
    reason: str | None = None,
    auth: AuthContext | None = None,
) -> Result[int, TriggerError]:
    """Pause all active triggers for a repository."""
    from syn_api.routes.triggers.queries import list_triggers

    list_result = await list_triggers(repository=repository, status="active", auth=auth)
    if isinstance(list_result, Err):
        return Err(list_result.error, message=list_result.message)

    paused_count = 0
    for trigger in list_result.value:
        result = await pause_trigger(
            trigger_id=trigger.trigger_id,
            reason=reason or f"Bulk disable for {repository}",
            paused_by=paused_by,
            auth=auth,
        )
        if isinstance(result, Ok):
            paused_count += 1

    return Ok(paused_count)


@router.post("", response_model=TriggerActionResponse)
async def register_trigger_endpoint(body: RegisterTriggerRequest) -> TriggerActionResponse:
    """Register a new trigger rule."""
    result = await register_trigger(
        name=body.name,
        event=body.event,
        repository=body.repository,
        workflow_id=body.workflow_id,
        conditions=body.conditions,
        installation_id=body.installation_id,
        input_mapping=body.input_mapping,
        config=body.config,
        created_by=body.created_by,
    )

    if isinstance(result, Err):
        raise HTTPException(status_code=400, detail=result.message)
    return TriggerActionResponse(trigger_id=result.value, name=body.name, status="active")


@router.post("/presets/{preset_name}", response_model=TriggerActionResponse)
async def enable_preset_endpoint(
    preset_name: str, body: EnablePresetRequest
) -> TriggerActionResponse:
    """Enable a preset for a repository."""
    result = await enable_preset(
        preset_name=preset_name,
        repository=body.repository,
        installation_id=body.installation_id,
        created_by=body.created_by,
        workflow_id=body.workflow_id,
    )
    if isinstance(result, Err):
        raise HTTPException(status_code=400, detail=result.message)
    return TriggerActionResponse(
        trigger_id=result.value,
        name=preset_name,
        status="active",
        preset=preset_name,
    )


@router.patch("/{trigger_id}", response_model=TriggerDetail, response_model_exclude_none=True)
async def update_trigger_endpoint(trigger_id: str, body: UpdateTriggerRequest) -> TriggerDetail:
    """Update trigger (pause/resume).

    Returns the full trigger detail with the authoritative status from the
    command result, not the projection. This avoids eventual consistency
    staleness — the caller sees the correct status immediately.
    """
    from .queries import _resolve_trigger_id, get_trigger

    trigger_id = await _resolve_trigger_id(trigger_id)
    if body.action == "pause":
        result = await pause_trigger(
            trigger_id=trigger_id,
            reason=body.reason,
            paused_by=body.paused_by,
        )
    else:
        result = await resume_trigger(
            trigger_id=trigger_id,
            resumed_by=body.resumed_by,
        )

    if isinstance(result, Err):
        raise HTTPException(
            status_code=409,
            detail=f"Cannot {body.action} trigger {trigger_id}: {result.message}",
        )

    # Map action to authoritative status (projection may not have caught up yet).
    status_map = {"pause": "paused", "resume": "active"}
    authoritative_status = status_map[body.action]

    # Read trigger detail from projection, then override status with the
    # authoritative command result.
    detail_result = await get_trigger(trigger_id)
    if isinstance(detail_result, Err):
        # Projection hasn't indexed this trigger — return minimal response
        return TriggerDetail(
            trigger_id=trigger_id,
            name="",
            event="",
            repository="",
            workflow_id="",
            status=authoritative_status,
        )

    detail = detail_result.value
    detail.status = authoritative_status
    return detail


@router.delete(
    "/{trigger_id}", response_model=TriggerActionResponse, response_model_exclude_none=True
)
async def delete_trigger_endpoint(trigger_id: str) -> TriggerActionResponse:
    """Delete a trigger rule."""
    from .queries import _resolve_trigger_id

    trigger_id = await _resolve_trigger_id(trigger_id)
    result = await delete_trigger(trigger_id=trigger_id, deleted_by="api")
    if isinstance(result, Err):
        raise HTTPException(
            status_code=409,
            detail=f"Cannot delete trigger {trigger_id}: {result.message}",
        )
    return TriggerActionResponse(trigger_id=trigger_id, status="deleted")
