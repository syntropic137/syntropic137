"""Trigger operations — register, manage, and query GitHub event triggers.

Maps to the github context in aef-domain.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from aef_api._wiring import (
    ensure_connected,
    get_trigger_repo,
    get_trigger_store,
    sync_published_events_to_projections,
)
from aef_api.types import (
    Err,
    Ok,
    Result,
    TriggerDetail,
    TriggerError,
    TriggerHistoryEntry,
    TriggerSummary,
)

if TYPE_CHECKING:
    from aef_api.auth import AuthContext


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
    """Register a new GitHub event trigger for a workflow.

    Args:
        name: Human-readable trigger name.
        event: GitHub event type (e.g. "push", "pull_request").
        repository: Target repository (owner/repo).
        workflow_id: Workflow to dispatch when triggered.
        conditions: Optional list of condition dicts.
        installation_id: GitHub App installation ID.
        input_mapping: Map of workflow input names to payload paths.
        config: Safety configuration dict.
        created_by: User or agent registering.
        auth: Optional authentication context.

    Returns:
        Ok(trigger_id) on success, Err(TriggerError) on failure.
    """
    from aef_domain.contexts.github.domain.commands.RegisterTriggerCommand import (
        RegisterTriggerCommand,
    )
    from aef_domain.contexts.github.slices.register_trigger.RegisterTriggerHandler import (
        RegisterTriggerHandler,
    )

    await ensure_connected()

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
        # Index trigger in the query store (projections may not run in test mode)
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
            config={},
            installation_id=aggregate.installation_id,
            created_by=aggregate.created_by,
            status=aggregate.status.value,
        )
        await sync_published_events_to_projections()
        return Ok(aggregate.trigger_id)
    except Exception as e:
        return Err(TriggerError.INVALID_INPUT, message=str(e))


async def enable_preset(
    preset_name: str,
    repository: str,
    installation_id: str = "",
    created_by: str = "system",
    auth: AuthContext | None = None,  # noqa: ARG001
) -> Result[str, TriggerError]:
    """Enable a built-in trigger preset for a repository.

    Args:
        preset_name: Preset name (e.g. "self-healing", "review-fix").
        repository: Target repository (owner/repo).
        installation_id: GitHub App installation ID.
        created_by: User or agent enabling the preset.
        auth: Optional authentication context.

    Returns:
        Ok(trigger_id) on success, Err(TriggerError) on failure.
    """
    from aef_domain.contexts.github._shared.trigger_presets import (
        create_preset_command,
    )
    from aef_domain.contexts.github.slices.register_trigger.RegisterTriggerHandler import (
        RegisterTriggerHandler,
    )

    await ensure_connected()

    try:
        command = create_preset_command(
            preset_name=preset_name,
            repository=repository,
            installation_id=installation_id,
            created_by=created_by,
        )
    except (ValueError, KeyError):
        return Err(
            TriggerError.PRESET_NOT_FOUND,
            message=f"Preset '{preset_name}' not found",
        )

    # Dedup check: skip if an active/paused trigger with the same name+repo+event exists
    existing = await list_triggers(repository=repository)
    if isinstance(existing, Ok):
        for t in existing.value:
            if t.name == command.name and t.event == command.event and t.status != "deleted":
                return Err(
                    TriggerError.INVALID_INPUT,
                    message=f"Trigger '{command.name}' already exists for {repository}",
                )

    store = get_trigger_store()
    repo = get_trigger_repo()
    handler = RegisterTriggerHandler(store=store, repository=repo)

    try:
        aggregate = await handler.handle(command)
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
            config={},
            installation_id=aggregate.installation_id,
            created_by=aggregate.created_by,
            status=aggregate.status.value,
        )
        await sync_published_events_to_projections()
        return Ok(aggregate.trigger_id)
    except Exception as e:
        return Err(TriggerError.INVALID_INPUT, message=str(e))


async def list_triggers(
    repository: str | None = None,
    status: str | None = None,
    auth: AuthContext | None = None,  # noqa: ARG001
) -> Result[list[TriggerSummary], TriggerError]:
    """List trigger rules with optional filters.

    Args:
        repository: Optional filter by repository.
        status: Optional filter by status (active, paused, deleted).
        auth: Optional authentication context.

    Returns:
        Ok(list[TriggerSummary]) on success, Err(TriggerError) on failure.
    """
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
                fire_count=getattr(t, "fire_count", 0),
                created_at=getattr(t, "created_at", None),
            )
            for t in triggers
        ]
    )


async def get_trigger(
    trigger_id: str,
    auth: AuthContext | None = None,  # noqa: ARG001
) -> Result[TriggerDetail, TriggerError]:
    """Get detailed information about a trigger rule.

    Args:
        trigger_id: The trigger rule ID.
        auth: Optional authentication context.

    Returns:
        Ok(TriggerDetail) on success, Err(TriggerError.NOT_FOUND) if missing.
    """
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
            fire_count=getattr(indexed, "fire_count", 0),
            created_at=getattr(indexed, "created_at", None),
            conditions=list(indexed.conditions) if indexed.conditions else [],
            input_mapping=dict(indexed.input_mapping) if indexed.input_mapping else {},
            config=dict(indexed.config) if isinstance(indexed.config, dict) else {},
            installation_id=getattr(indexed, "installation_id", "") or "",
            created_by=getattr(indexed, "created_by", "") or "",
            last_fired_at=getattr(indexed, "last_fired_at", None),
        )
    )


def get_trigger_history(
    trigger_id: str,
    limit: int = 50,
    auth: AuthContext | None = None,  # noqa: ARG001
) -> Result[list[TriggerHistoryEntry], TriggerError]:
    """Get execution history for a trigger rule.

    Note: This is a synchronous function (the handler is sync).

    Args:
        trigger_id: The trigger rule ID.
        limit: Maximum number of history entries to return.
        auth: Optional authentication context.

    Returns:
        Ok(list[TriggerHistoryEntry]) on success, Err(TriggerError) on failure.
    """
    from aef_domain.contexts.github.domain.queries.get_trigger_history import (
        GetTriggerHistoryQuery,
    )
    from aef_domain.contexts.github.slices.trigger_history.handler import (
        get_trigger_history_handler,
    )

    try:
        query = GetTriggerHistoryQuery(trigger_id=trigger_id, limit=limit)
    except ValueError as e:
        return Err(TriggerError.INVALID_INPUT, message=str(e))

    handler = get_trigger_history_handler()
    entries = handler.handle(query)

    return Ok(
        [
            TriggerHistoryEntry(
                trigger_id=e.trigger_id,
                execution_id=e.execution_id,
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


async def pause_trigger(
    trigger_id: str,
    reason: str | None = None,
    paused_by: str = "",
    auth: AuthContext | None = None,  # noqa: ARG001
) -> Result[None, TriggerError]:
    """Pause an active trigger.

    Args:
        trigger_id: The trigger rule ID to pause.
        reason: Optional reason for pausing.
        paused_by: User or agent pausing.
        auth: Optional authentication context.

    Returns:
        Ok(None) on success, Err(TriggerError) on failure.
    """
    from aef_domain.contexts.github.domain.commands.PauseTriggerCommand import (
        PauseTriggerCommand,
    )
    from aef_domain.contexts.github.slices.manage_trigger.ManageTriggerHandler import (
        ManageTriggerHandler,
    )

    await ensure_connected()
    store = get_trigger_store()

    # Check current state
    indexed = await store.get(trigger_id)
    if indexed is None:
        return Err(TriggerError.NOT_FOUND, message=f"Trigger {trigger_id} not found")
    if indexed.status == "paused":
        return Err(TriggerError.ALREADY_PAUSED)
    if indexed.status == "deleted":
        return Err(TriggerError.ALREADY_DELETED)

    command = PauseTriggerCommand(
        trigger_id=trigger_id,
        paused_by=paused_by,
        reason=reason,
    )

    repo = get_trigger_repo()
    handler = ManageTriggerHandler(store=store, repository=repo)
    result = await handler.pause(command)

    if result is None:
        return Err(TriggerError.NOT_FOUND, message=f"Failed to pause trigger {trigger_id}")

    await store.update_status(trigger_id, "paused")
    await sync_published_events_to_projections()
    return Ok(None)


async def resume_trigger(
    trigger_id: str,
    resumed_by: str = "",
    auth: AuthContext | None = None,  # noqa: ARG001
) -> Result[None, TriggerError]:
    """Resume a paused trigger.

    Args:
        trigger_id: The trigger rule ID to resume.
        resumed_by: User or agent resuming.
        auth: Optional authentication context.

    Returns:
        Ok(None) on success, Err(TriggerError) on failure.
    """
    from aef_domain.contexts.github.domain.commands.ResumeTriggerCommand import (
        ResumeTriggerCommand,
    )
    from aef_domain.contexts.github.slices.manage_trigger.ManageTriggerHandler import (
        ManageTriggerHandler,
    )

    await ensure_connected()
    store = get_trigger_store()

    # Check current state
    indexed = await store.get(trigger_id)
    if indexed is None:
        return Err(TriggerError.NOT_FOUND, message=f"Trigger {trigger_id} not found")
    if indexed.status == "active":
        return Err(TriggerError.ALREADY_ACTIVE)
    if indexed.status == "deleted":
        return Err(TriggerError.ALREADY_DELETED)

    command = ResumeTriggerCommand(
        trigger_id=trigger_id,
        resumed_by=resumed_by,
    )

    repo = get_trigger_repo()
    handler = ManageTriggerHandler(store=store, repository=repo)
    result = await handler.resume(command)

    if result is None:
        return Err(TriggerError.NOT_FOUND, message=f"Failed to resume trigger {trigger_id}")

    await store.update_status(trigger_id, "active")
    await sync_published_events_to_projections()
    return Ok(None)


async def delete_trigger(
    trigger_id: str,
    deleted_by: str = "",
    auth: AuthContext | None = None,  # noqa: ARG001
) -> Result[None, TriggerError]:
    """Soft-delete a trigger rule.

    Args:
        trigger_id: The trigger rule ID to delete.
        deleted_by: User or agent deleting.
        auth: Optional authentication context.

    Returns:
        Ok(None) on success, Err(TriggerError) on failure.
    """
    from aef_domain.contexts.github.domain.commands.DeleteTriggerCommand import (
        DeleteTriggerCommand,
    )
    from aef_domain.contexts.github.slices.manage_trigger.ManageTriggerHandler import (
        ManageTriggerHandler,
    )

    await ensure_connected()
    store = get_trigger_store()

    # Check current state
    indexed = await store.get(trigger_id)
    if indexed is None:
        return Err(TriggerError.NOT_FOUND, message=f"Trigger {trigger_id} not found")
    if indexed.status == "deleted":
        return Err(TriggerError.ALREADY_DELETED)

    command = DeleteTriggerCommand(
        trigger_id=trigger_id,
        deleted_by=deleted_by,
    )

    repo = get_trigger_repo()
    handler = ManageTriggerHandler(store=store, repository=repo)
    result = await handler.delete(command)

    if result is None:
        return Err(TriggerError.NOT_FOUND, message=f"Failed to delete trigger {trigger_id}")

    await store.update_status(trigger_id, "deleted")
    await sync_published_events_to_projections()
    return Ok(None)


async def disable_triggers(
    repository: str,
    paused_by: str = "",
    reason: str | None = None,
    auth: AuthContext | None = None,
) -> Result[int, TriggerError]:
    """Pause all active triggers for a repository.

    Args:
        repository: Repository (owner/repo) to disable triggers for.
        paused_by: User or agent pausing.
        reason: Optional reason for pausing.
        auth: Optional authentication context.

    Returns:
        Ok(count) with number of triggers paused, Err(TriggerError) on failure.
    """
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
