"""Trigger command operations and write endpoints."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from syn_adapters.repo_names import OrganizationRepoNames
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
    TriggerErrorResponse,
)
from syn_domain.contexts.github import TriggerStatus

if TYPE_CHECKING:
    from syn_domain.contexts.github._shared.trigger_query_store import TriggerQueryStore
    from syn_domain.contexts.github.domain.aggregate_trigger.TriggerRuleAggregate import (
        TriggerRuleAggregate,
    )

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/triggers", tags=["triggers"])


async def _github_name(repository: str) -> str:
    """The repository as GitHub names it when it resolves, else as given.

    The CLI registers triggers by syn137 `repo-*` id. Stored as given, the id
    reached the event poller, which cannot poll it (#1870), and event matching,
    which compares against GitHub's `owner/name`.
    """
    return await OrganizationRepoNames().full_name(repository) or repository


async def _resolve_installation_id(
    installation_id: str, repository: str
) -> Result[str, TriggerError]:
    """Resolve the GitHub App installation a trigger on `repository` fires through.

    The CLI registers triggers with syn `repo-*` IDs. Those are unknown to the
    GitHub API, so we first resolve them to `owner/name` via the repo
    projection, then ask the App which installation owns that repo.

    An explicit `installation_id`, or a trigger with no repository, is taken
    as given. Otherwise a rule with no installation can never fire: dispatch
    skips it (``event_ingestion._get_repos_to_poll``). So every way resolution
    can fail is an `Err` and the caller refuses the registration, rather than
    storing an `active` rule that is silently dead (#1864).
    """
    if installation_id or not repository:
        return Ok(installation_id)

    full_name = await OrganizationRepoNames().full_name(repository)
    if full_name is None:
        return Err(
            TriggerError.REPOSITORY_UNRESOLVED,
            message=(
                f"Repository '{repository}' is neither a registered repo ID nor "
                "'owner/name', so no GitHub App installation can be found for it."
            ),
        )

    from syn_adapters.github.client import (
        GitHubAppError,
        GitHubAuthError,
        GitHubNotConfiguredError,
        get_github_client,
    )

    try:
        resolved = await get_github_client().get_installation_for_repo(full_name)
    except GitHubNotConfiguredError as e:
        # The same words `GET /github/repos` answers with (baca940).
        return Err(TriggerError.GITHUB_NOT_CONFIGURED, message=str(e))
    except GitHubAuthError as e:
        return Err(
            TriggerError.NO_INSTALLATION,
            message=(f"{e}. Install the GitHub App on {full_name}, then create the trigger again."),
        )
    except GitHubAppError as e:
        logger.warning("could not resolve installation for %s", full_name, exc_info=True)
        return Err(
            TriggerError.GITHUB_UNAVAILABLE,
            message=(
                f"Could not ask GitHub which installation covers {full_name} "
                f"({type(e).__name__}: {e}). Nothing was stored; try again."
            ),
        )
    logger.info("Auto-resolved installation_id=%s for %s", resolved, full_name)
    return Ok(str(resolved))


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
    repository = await _github_name(repository)
    resolved = await _resolve_installation_id(installation_id, repository)
    if isinstance(resolved, Err):
        return resolved
    installation_id = resolved.value

    workflow_repo = get_workflow_repo()
    # `exists` RAISES when the store cannot be read (ESP #310). Before that it
    # answered False, so an outage reached this branch as "no such workflow" -
    # a confident wrong answer. Catching it here keeps the two apart instead of
    # letting the exception escape as a 500 with no explanation.
    try:
        workflow_exists = await workflow_repo.exists(workflow_id)
    except Exception as exc:
        logger.warning("could not determine whether workflow %s exists", workflow_id, exc_info=True)
        return Err(
            TriggerError.STORE_UNAVAILABLE,
            message=(
                f"Could not determine whether workflow '{workflow_id}' exists: "
                f"the event store could not be read ({type(exc).__name__}). "
                "This is not a statement that the workflow is missing."
            ),
        )
    if not workflow_exists:
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
    repository = await _github_name(repository)
    resolved = await _resolve_installation_id(installation_id, repository)
    if isinstance(resolved, Err):
        return resolved
    installation_id = resolved.value

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
    # Same distinction as above: an unreadable store is not a missing workflow.
    try:
        workflow_exists = await workflow_repo.exists(command.workflow_id)
    except Exception as exc:
        logger.warning(
            "could not determine whether workflow %s exists", command.workflow_id, exc_info=True
        )
        return Err(
            TriggerError.STORE_UNAVAILABLE,
            message=(
                f"Could not determine whether workflow '{command.workflow_id}' exists: "
                f"the event store could not be read ({type(exc).__name__}). "
                "This is not a statement that the workflow is missing."
            ),
        )
    if not workflow_exists:
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


# 409, not 422: the request is well-formed and the same body succeeds once an
# operator configures the App or installs it on the repo. What it conflicts
# with is the server's state. 422 is also FastAPI's own validation answer,
# whose `detail` is a list, so sharing it would give clients two shapes to tell
# apart on one status code (#1864).
_TRIGGER_ERROR_STATUS: dict[TriggerError, int] = {
    TriggerError.GITHUB_NOT_CONFIGURED: 409,
    TriggerError.NO_INSTALLATION: 409,
    TriggerError.REPOSITORY_UNRESOLVED: 409,
    TriggerError.GITHUB_UNAVAILABLE: 503,
}

_CREATE_RESPONSES: dict[int | str, dict[str, type[TriggerErrorResponse] | str]] = {
    400: {"model": TriggerErrorResponse, "description": "Invalid request; nothing stored"},
    409: {
        "model": TriggerErrorResponse,
        "description": (
            "Refused: the trigger could never fire. No GitHub App is configured, "
            "no installation covers the repository, or the repository is unknown. "
            "Nothing stored."
        ),
    },
    503: {
        "model": TriggerErrorResponse,
        "description": "GitHub could not be asked for the installation; nothing stored",
    },
}


def _trigger_error_response(err: Err[TriggerError]) -> JSONResponse:
    """Render a refused trigger creation as its declared error body."""
    body = TriggerErrorResponse(detail=err.message or err.error.value, code=err.error)
    return JSONResponse(
        status_code=_TRIGGER_ERROR_STATUS.get(err.error, 400), content=body.model_dump()
    )


@router.post("", response_model=TriggerActionResponse, responses=_CREATE_RESPONSES)
async def register_trigger_endpoint(
    body: RegisterTriggerRequest,
) -> TriggerActionResponse | JSONResponse:
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
        return _trigger_error_response(result)
    return TriggerActionResponse(trigger_id=result.value, name=body.name, status="active")


@router.post(
    "/presets/{preset_name}", response_model=TriggerActionResponse, responses=_CREATE_RESPONSES
)
async def enable_preset_endpoint(
    preset_name: str, body: dict[str, Any]
) -> TriggerActionResponse | JSONResponse:
    """Enable a preset for a repository."""
    repository = body.get("repository", "")
    if not repository:
        return _trigger_error_response(
            Err(TriggerError.INVALID_INPUT, message="repository is required")
        )

    result = await enable_preset(
        preset_name=preset_name,
        repository=repository,
        installation_id=body.get("installation_id", ""),
        created_by=body.get("created_by", "api"),
        workflow_id=body.get("workflow_id", ""),
    )
    if isinstance(result, Err):
        return _trigger_error_response(result)
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
