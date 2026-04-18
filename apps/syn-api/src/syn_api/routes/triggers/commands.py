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
    Err,
    Ok,
    RegisterTriggerRequest,
    Result,
    TriggerActionResponse,
    TriggerError,
)
from syn_domain.contexts.github import TriggerStatus

if TYPE_CHECKING:
    from syn_domain.contexts.github._shared.trigger_query_store import TriggerQueryStore
    from syn_domain.contexts.github.domain.aggregate_trigger.TriggerRuleAggregate import (
        TriggerRuleAggregate,
    )

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/triggers", tags=["triggers"])


async def _resolve_repo_full_name(repository: str) -> str | None:
    """Resolve a repository identifier to its GitHub `owner/name` form.

    - `repo-*` (syn internal ID): look up via the repo projection.
    - `owner/name` (GitHub standard): passed through.
    - Anything else: `None` (caller treats as unresolvable).
    """
    if repository.startswith("repo-"):
        from syn_domain.contexts.organization import get_repo_projection

        projection = get_repo_projection()
        repo = await projection.get(repository)
        return repo.full_name if repo is not None else None

    if "/" in repository:
        return repository

    return None


async def _resolve_installation_id(installation_id: str, repository: str) -> str:
    """Auto-resolve installation_id from the GitHub App if not provided.

    P0-3: the CLI registers triggers with syn `repo-*` IDs. Those are
    unknown to the GitHub API, so we first resolve them to `owner/name`
    via the repo projection, then ask the App which installation owns
    that repo. Returns `""` if resolution fails at any step — the poller
    re-resolves on first fire.
    """
    if installation_id or not repository:
        return installation_id

    full_name = await _resolve_repo_full_name(repository)
    if full_name is None:
        logger.warning(
            "Could not resolve repository identifier '%s' to owner/name; "
            "trigger will be persisted with installation_id='' and re-resolve later",
            repository,
        )
        return ""

    try:
        from syn_adapters.github.client import get_github_client

        client = get_github_client()
        resolved = await client.get_installation_for_repo(full_name)
        logger.info("Auto-resolved installation_id=%s for %s", resolved, full_name)
        return str(resolved)
    except Exception:
        logger.warning(
            "Could not auto-resolve installation_id for %s",
            full_name,
            exc_info=True,
        )
        return ""


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
) -> Result[str, TriggerError]:
    """Register a new GitHub event trigger for a workflow."""
    from syn_domain.contexts.github import RegisterTriggerCommand, RegisterTriggerHandler

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


async def _index_and_sync_trigger(
    store: TriggerQueryStore, aggregate: TriggerRuleAggregate
) -> None:
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
) -> Result[str, TriggerError]:
    """Enable a built-in trigger preset for a repository."""
    from syn_domain.contexts.github import RegisterTriggerHandler, create_preset_command

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
) -> Result[None, TriggerError]:
    """Pause an active trigger."""
    from syn_domain.contexts.github import ManageTriggerHandler, PauseTriggerCommand

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
) -> Result[None, TriggerError]:
    """Resume a paused trigger."""
    from syn_domain.contexts.github import ManageTriggerHandler, ResumeTriggerCommand

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
) -> Result[None, TriggerError]:
    """Soft-delete a trigger rule."""
    from syn_domain.contexts.github import DeleteTriggerCommand, ManageTriggerHandler

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
) -> Result[int, TriggerError]:
    """Pause all active triggers for a repository."""
    from syn_api.routes.triggers.queries import list_triggers

    list_result = await list_triggers(repository=repository, status="active")
    if isinstance(list_result, Err):
        return Err(list_result.error, message=list_result.message)

    paused_count = 0
    for trigger in list_result.value:
        result = await pause_trigger(
            trigger_id=trigger.trigger_id,
            reason=reason or f"Bulk disable for {repository}",
            paused_by=paused_by,
        )
        if isinstance(result, Ok):
            paused_count += 1

    return Ok(paused_count)


@router.post("", response_model=TriggerActionResponse)
async def register_trigger_endpoint(body: RegisterTriggerRequest) -> TriggerActionResponse:
    """Register a new trigger rule."""
    cfg = body.config
    config_dict: dict[str, object] | None = (
        {
            "max_attempts": cfg.max_attempts,
            "daily_limit": cfg.daily_limit,
            "debounce_seconds": cfg.debounce_seconds,
            "cooldown_seconds": cfg.cooldown_seconds,
        }
        if cfg is not None
        else None
    )
    result = await register_trigger(
        name=body.name,
        event=body.event,
        repository=body.repository,
        workflow_id=body.workflow_id,
        conditions=[
            {"field": c.field, "operator": c.operator, "value": c.value}
            for c in (body.conditions or [])
        ],
        installation_id=body.installation_id,
        input_mapping=dict(body.input_mapping) if body.input_mapping else None,
        config=config_dict,
        created_by=body.created_by,
    )

    if isinstance(result, Err):
        raise HTTPException(status_code=400, detail=result.message)
    return TriggerActionResponse(trigger_id=result.value, name=body.name, status="active")


@router.post("/presets/{preset_name}", response_model=TriggerActionResponse)
async def enable_preset_endpoint(preset_name: str, body: dict[str, Any]) -> TriggerActionResponse:
    """Enable a preset for a repository."""
    repository = body.get("repository", "")
    if not repository:
        raise HTTPException(status_code=400, detail="repository is required")

    result = await enable_preset(
        preset_name=preset_name,
        repository=repository,
        installation_id=body.get("installation_id", ""),
        created_by=body.get("created_by", "api"),
        workflow_id=body.get("workflow_id", ""),
    )
    if isinstance(result, Err):
        raise HTTPException(status_code=400, detail=result.message)
    return TriggerActionResponse(
        trigger_id=result.value,
        name=preset_name,
        status="active",
        preset=preset_name,
    )


@router.patch(
    "/{trigger_id}", response_model=TriggerActionResponse, response_model_exclude_none=True
)
async def update_trigger_endpoint(trigger_id: str, body: dict[str, Any]) -> TriggerActionResponse:
    """Update trigger (pause/resume)."""
    from .queries import _resolve_trigger_id

    trigger_id = await _resolve_trigger_id(trigger_id)
    action = body.get("action", "")
    if action == "pause":
        result = await pause_trigger(
            trigger_id=trigger_id,
            reason=body.get("reason"),
            paused_by=body.get("paused_by", "api"),
        )
    elif action == "resume":
        result = await resume_trigger(
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
    return TriggerActionResponse(trigger_id=trigger_id, status=action + "d", action=action)


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
