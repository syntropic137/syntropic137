"""Repo management API endpoints and service operations.

Provides CRUD for repos with domain aggregate interaction,
plus insight queries (health, cost, activity, failures, sessions).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, HTTPException

from syn_api._wiring import (
    ensure_connected,
    sync_published_events_to_projections,
)
from syn_api.types import (
    Err,
    Ok,
    RepoError,
    RepoSummaryResponse,
    Result,
)

if TYPE_CHECKING:
    from syn_api.auth import AuthContext

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/repos", tags=["repos"])


# =============================================================================
# Service functions (importable by tests)
# =============================================================================


async def register_repo(
    organization_id: str,
    provider: str,
    full_name: str,
    owner: str = "",
    default_branch: str = "main",
    provider_repo_id: str = "",
    installation_id: str = "",
    is_private: bool = False,
    created_by: str = "",
    auth: AuthContext | None = None,  # noqa: ARG001
) -> Result[str, RepoError]:
    """Register a new repo within an organization."""
    from syn_adapters.storage.repositories import get_repo_repository
    from syn_domain.contexts.organization.domain.commands.RegisterRepoCommand import (
        RegisterRepoCommand,
    )
    from syn_domain.contexts.organization.slices.register_repo.RegisterRepoHandler import (
        RegisterRepoHandler,
    )

    await ensure_connected()

    try:
        command = RegisterRepoCommand(
            organization_id=organization_id,
            provider=provider,
            full_name=full_name,
            owner=owner,
            default_branch=default_branch,
            provider_repo_id=provider_repo_id,
            installation_id=installation_id,
            is_private=is_private,
            created_by=created_by,
        )
    except ValueError as e:
        return Err(RepoError.INVALID_INPUT, message=str(e))

    repo = get_repo_repository()
    handler = RegisterRepoHandler(repository=repo)

    try:
        aggregate = await handler.handle(command)
        await sync_published_events_to_projections()
        return Ok(aggregate.repo_id)
    except Exception as e:
        return Err(RepoError.INVALID_INPUT, message=str(e))


async def list_repos(
    organization_id: str | None = None,
    system_id: str | None = None,
    provider: str | None = None,
    unassigned: bool = False,
    auth: AuthContext | None = None,  # noqa: ARG001
) -> Result[list[RepoSummaryResponse], RepoError]:
    """List repos with optional filters."""
    from syn_domain.contexts.organization.slices.list_repos.projection import (
        get_repo_projection,
    )

    await ensure_connected()

    projection = get_repo_projection()
    repos = await projection.list_all(
        organization_id=organization_id,
        system_id=system_id,
        provider=provider,
        unassigned=unassigned,
    )

    return Ok(
        [
            RepoSummaryResponse(
                repo_id=r.repo_id,
                organization_id=r.organization_id,
                system_id=r.system_id,
                provider=r.provider,
                full_name=r.full_name,
                owner=r.owner,
                default_branch=r.default_branch,
                installation_id=r.installation_id,
                is_private=r.is_private,
                created_by=r.created_by,
                created_at=r.created_at,
            )
            for r in repos
        ]
    )


async def get_repo(
    repo_id: str,
    auth: AuthContext | None = None,  # noqa: ARG001
) -> Result[RepoSummaryResponse, RepoError]:
    """Get repo details."""
    from syn_domain.contexts.organization.slices.list_repos.projection import (
        get_repo_projection,
    )

    await ensure_connected()

    projection = get_repo_projection()
    repo = await projection.get(repo_id)

    if repo is None:
        return Err(RepoError.NOT_FOUND, message=f"Repo {repo_id} not found")

    return Ok(
        RepoSummaryResponse(
            repo_id=repo.repo_id,
            organization_id=repo.organization_id,
            system_id=repo.system_id,
            provider=repo.provider,
            full_name=repo.full_name,
            owner=repo.owner,
            default_branch=repo.default_branch,
            installation_id=repo.installation_id,
            is_private=repo.is_private,
            created_by=repo.created_by,
            created_at=repo.created_at,
        )
    )


async def assign_repo_to_system(
    repo_id: str,
    system_id: str,
    auth: AuthContext | None = None,  # noqa: ARG001
) -> Result[None, RepoError]:
    """Assign a repo to a system."""
    from syn_adapters.storage.repositories import get_repo_repository
    from syn_domain.contexts.organization.domain.commands.AssignRepoToSystemCommand import (
        AssignRepoToSystemCommand,
    )
    from syn_domain.contexts.organization.slices.manage_repo.ManageRepoHandler import (
        ManageRepoHandler,
    )

    await ensure_connected()

    try:
        command = AssignRepoToSystemCommand(
            repo_id=repo_id,
            system_id=system_id,
        )
    except ValueError as e:
        return Err(RepoError.INVALID_INPUT, message=str(e))

    repo = get_repo_repository()
    handler = ManageRepoHandler(repository=repo)
    result = await handler.assign_to_system(command)

    if result is None:
        return Err(RepoError.NOT_FOUND, message=f"Repo {repo_id} not found")

    if not result.success:
        error_enum = _classify_repo_error(result.error)
        return Err(error_enum, message=result.error)

    await sync_published_events_to_projections()
    return Ok(None)


async def unassign_repo_from_system(
    repo_id: str,
    auth: AuthContext | None = None,  # noqa: ARG001
) -> Result[None, RepoError]:
    """Unassign a repo from its system."""
    from syn_adapters.storage.repositories import get_repo_repository
    from syn_domain.contexts.organization.domain.commands.UnassignRepoFromSystemCommand import (
        UnassignRepoFromSystemCommand,
    )
    from syn_domain.contexts.organization.slices.manage_repo.ManageRepoHandler import (
        ManageRepoHandler,
    )

    await ensure_connected()

    try:
        command = UnassignRepoFromSystemCommand(repo_id=repo_id)
    except ValueError as e:
        return Err(RepoError.INVALID_INPUT, message=str(e))

    repo = get_repo_repository()
    handler = ManageRepoHandler(repository=repo)
    result = await handler.unassign_from_system(command)

    if result is None:
        return Err(RepoError.NOT_FOUND, message=f"Repo {repo_id} not found")

    if not result.success:
        error_enum = _classify_repo_error(result.error)
        return Err(error_enum, message=result.error)

    await sync_published_events_to_projections()
    return Ok(None)


# ---------------------------------------------------------------------------
# Insight queries — repo-level health, cost, activity, failures, sessions
# ---------------------------------------------------------------------------


async def get_repo_health(repo_id: str) -> Result[dict[str, Any], RepoError]:
    """Get health snapshot for a repo."""
    from syn_api._wiring import get_projection_mgr
    from syn_domain.contexts.organization.domain.queries.get_repo_health import (
        GetRepoHealthQuery,
    )
    from syn_domain.contexts.organization.slices.repo_health.GetRepoHealthHandler import (
        GetRepoHealthHandler,
    )

    await ensure_connected()

    repo_result = await get_repo(repo_id)
    if not isinstance(repo_result, Ok):
        return Err(RepoError.NOT_FOUND, message=f"Repo {repo_id} not found")

    mgr = get_projection_mgr()
    handler = GetRepoHealthHandler(projection=mgr.repo_health)
    result = await handler.handle(
        GetRepoHealthQuery(repo_id=repo_id, repo_full_name=repo_result.value.full_name)
    )
    return Ok(dict(result.to_dict()))


async def get_repo_cost(repo_id: str) -> Result[dict[str, Any], RepoError]:
    """Get cost breakdown for a repo."""
    from syn_api._wiring import get_projection_mgr
    from syn_domain.contexts.organization.domain.queries.get_repo_cost import (
        GetRepoCostQuery,
    )
    from syn_domain.contexts.organization.slices.repo_cost.GetRepoCostHandler import (
        GetRepoCostHandler,
    )

    await ensure_connected()

    repo_result = await get_repo(repo_id)
    if not isinstance(repo_result, Ok):
        return Err(RepoError.NOT_FOUND, message=f"Repo {repo_id} not found")

    mgr = get_projection_mgr()
    handler = GetRepoCostHandler(projection=mgr.repo_cost)
    result = await handler.handle(
        GetRepoCostQuery(repo_id=repo_id, repo_full_name=repo_result.value.full_name)
    )
    return Ok(dict(result.to_dict()))


async def get_repo_activity(
    repo_id: str, offset: int = 0, limit: int = 50
) -> Result[list[dict[str, Any]], RepoError]:
    """Get execution timeline for a repo."""
    from syn_adapters.projection_stores import get_projection_store
    from syn_domain.contexts.organization.domain.queries.get_repo_activity import (
        GetRepoActivityQuery,
    )
    from syn_domain.contexts.organization.slices.repo_activity.GetRepoActivityHandler import (
        GetRepoActivityHandler,
    )

    await ensure_connected()

    repo_result = await get_repo(repo_id)
    if not isinstance(repo_result, Ok):
        return Err(RepoError.NOT_FOUND, message=f"Repo {repo_id} not found")

    handler = GetRepoActivityHandler(store=get_projection_store())
    entries = await handler.handle(
        GetRepoActivityQuery(repo_id=repo_id, offset=offset, limit=limit)
    )
    return Ok([e.to_dict() for e in entries])


async def get_repo_failures(
    repo_id: str, limit: int = 50
) -> Result[list[dict[str, Any]], RepoError]:
    """Get recent failures for a repo."""
    from syn_adapters.projection_stores import get_projection_store
    from syn_domain.contexts.organization.domain.queries.get_repo_failures import (
        GetRepoFailuresQuery,
    )
    from syn_domain.contexts.organization.slices.repo_failures.GetRepoFailuresHandler import (
        GetRepoFailuresHandler,
    )

    await ensure_connected()

    repo_result = await get_repo(repo_id)
    if not isinstance(repo_result, Ok):
        return Err(RepoError.NOT_FOUND, message=f"Repo {repo_id} not found")

    handler = GetRepoFailuresHandler(store=get_projection_store())
    entries = await handler.handle(GetRepoFailuresQuery(repo_id=repo_id, limit=limit))
    return Ok([e.to_dict() for e in entries])


async def get_repo_sessions(
    repo_id: str, limit: int = 50
) -> Result[list[dict[str, Any]], RepoError]:
    """Get agent sessions for a repo."""
    from syn_adapters.projection_stores import get_projection_store
    from syn_domain.contexts.organization.domain.queries.get_repo_sessions import (
        GetRepoSessionsQuery,
    )
    from syn_domain.contexts.organization.slices.repo_sessions.GetRepoSessionsHandler import (
        GetRepoSessionsHandler,
    )

    await ensure_connected()

    repo_result = await get_repo(repo_id)
    if not isinstance(repo_result, Ok):
        return Err(RepoError.NOT_FOUND, message=f"Repo {repo_id} not found")

    handler = GetRepoSessionsHandler(store=get_projection_store())
    results = await handler.handle(GetRepoSessionsQuery(repo_id=repo_id, limit=limit))
    return Ok([r.to_dict() for r in results])


async def update_repo(
    repo_id: str,
    default_branch: str | None = None,
    is_private: bool | None = None,
    installation_id: str | None = None,
    updated_by: str = "",
    auth: AuthContext | None = None,  # noqa: ARG001
) -> Result[None, RepoError]:
    """Update mutable fields of a repo."""
    from syn_adapters.storage.repositories import get_repo_repository
    from syn_domain.contexts.organization.domain.commands.UpdateRepoCommand import (
        UpdateRepoCommand,
    )
    from syn_domain.contexts.organization.slices.manage_repo.ManageRepoHandler import (
        ManageRepoHandler,
    )

    await ensure_connected()

    try:
        command = UpdateRepoCommand(
            repo_id=repo_id,
            default_branch=default_branch,
            is_private=is_private,
            installation_id=installation_id,
            updated_by=updated_by,
        )
    except ValueError as e:
        return Err(RepoError.INVALID_INPUT, message=str(e))

    repo = get_repo_repository()
    handler = ManageRepoHandler(repository=repo)
    result = await handler.update(command)

    if result is None:
        return Err(RepoError.NOT_FOUND, message=f"Repo {repo_id} not found")

    if not result.success:
        error_enum = _classify_repo_error(result.error)
        return Err(error_enum, message=result.error)

    await sync_published_events_to_projections()
    return Ok(None)


async def _check_active_triggers(repo_id: str, full_name: str | None) -> Result[None, RepoError]:
    """Cross-context guard: reject if active trigger rules reference this repo."""
    if full_name is None:
        return Ok(None)
    try:
        from syn_domain.contexts.github.slices.list_triggers.projection import (
            get_trigger_rule_projection,
        )

        trigger_projection = get_trigger_rule_projection()
        triggers = await trigger_projection.list_all()
        active = [t for t in triggers if t.repository == full_name and t.status == "active"]
        if active:
            names = ", ".join(t.name for t in active[:3])
            return Err(
                RepoError.HAS_ACTIVE_TRIGGERS,
                message=f"Repo has {len(active)} active trigger(s): {names}",
            )
    except Exception:
        logger.warning("Could not check trigger rules for repo %s", repo_id, exc_info=True)
        return Err(
            RepoError.TRIGGER_CHECK_FAILED,
            message="Could not verify trigger rule status",
        )
    return Ok(None)


async def deregister_repo(
    repo_id: str,
    deregistered_by: str = "",
    auth: AuthContext | None = None,  # noqa: ARG001
) -> Result[None, RepoError]:
    """Deregister (soft-delete) a repo.

    Cross-context guard: rejects if active trigger rules reference this repo.
    """
    from syn_adapters.storage.repositories import get_repo_repository
    from syn_domain.contexts.organization.domain.commands.DeregisterRepoCommand import (
        DeregisterRepoCommand,
    )
    from syn_domain.contexts.organization.slices.manage_repo.ManageRepoHandler import (
        ManageRepoHandler,
    )

    await ensure_connected()

    repo_result = await get_repo(repo_id)
    repo_full_name: str | None = None
    if isinstance(repo_result, Ok):
        repo_full_name = repo_result.value.full_name

    trigger_check = await _check_active_triggers(repo_id, repo_full_name)
    if isinstance(trigger_check, Err):
        return trigger_check

    try:
        command = DeregisterRepoCommand(
            repo_id=repo_id,
            deregistered_by=deregistered_by,
        )
    except ValueError as e:
        return Err(RepoError.INVALID_INPUT, message=str(e))

    repo = get_repo_repository()
    handler = ManageRepoHandler(repository=repo)
    result = await handler.deregister(command)

    if result is None:
        return Err(RepoError.NOT_FOUND, message=f"Repo {repo_id} not found")

    if not result.success:
        error_enum = _classify_repo_error(result.error)
        return Err(error_enum, message=result.error)

    await sync_published_events_to_projections()
    return Ok(None)


def _classify_repo_error(error_msg: str) -> RepoError:
    """Map a domain ValueError message to a specific RepoError."""
    lower = error_msg.lower()
    if "already assigned" in lower:
        return RepoError.ALREADY_ASSIGNED
    if "not assigned" in lower:
        return RepoError.NOT_ASSIGNED
    if "deregistered" in lower:
        return RepoError.ALREADY_DEREGISTERED
    return RepoError.INVALID_INPUT


# =============================================================================
# HTTP Endpoints
# =============================================================================


@router.post("")
async def register_repo_endpoint(body: dict[str, Any]) -> dict[str, Any]:
    """Register a new repo."""
    try:
        result = await register_repo(
            organization_id=body["organization_id"],
            provider=body.get("provider", "github"),
            full_name=body["full_name"],
            owner=body.get("owner", ""),
            default_branch=body.get("default_branch", "main"),
            provider_repo_id=body.get("provider_repo_id", ""),
            installation_id=body.get("installation_id", ""),
            is_private=body.get("is_private", False),
            created_by=body.get("created_by", "api"),
        )
    except (KeyError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    if isinstance(result, Err):
        raise HTTPException(status_code=400, detail=result.message)

    return {"repo_id": result.value, "full_name": body["full_name"]}


@router.get("")
async def list_repos_endpoint(
    organization_id: str | None = None,
    system_id: str | None = None,
    provider: str | None = None,
    unassigned: bool = False,
) -> dict[str, Any]:
    """List repos with optional filters."""
    result = await list_repos(
        organization_id=organization_id,
        system_id=system_id,
        provider=provider,
        unassigned=unassigned,
    )

    if isinstance(result, Err):
        raise HTTPException(status_code=500, detail=result.message)

    return {
        "repos": [r.model_dump() for r in result.value],
        "total": len(result.value),
    }


@router.get("/{repo_id}")
async def get_repo_endpoint(repo_id: str) -> dict[str, Any]:
    """Get repo details."""
    result = await get_repo(repo_id)

    if isinstance(result, Err):
        raise HTTPException(status_code=404, detail=result.message)

    return result.value.model_dump()


@router.put("/{repo_id}")
async def update_repo_endpoint(repo_id: str, body: dict[str, Any]) -> dict[str, Any]:
    """Update mutable fields of a repo."""
    result = await update_repo(
        repo_id=repo_id,
        default_branch=body.get("default_branch"),
        is_private=body.get("is_private"),
        installation_id=body.get("installation_id"),
        updated_by=body.get("updated_by", "api"),
    )

    if isinstance(result, Err):
        if result.error == RepoError.NOT_FOUND:
            raise HTTPException(status_code=404, detail=result.message)
        if result.error == RepoError.ALREADY_DEREGISTERED:
            raise HTTPException(status_code=409, detail=result.message)
        raise HTTPException(status_code=400, detail=result.message)

    return {"repo_id": repo_id, "status": "updated"}


@router.delete("/{repo_id}")
async def deregister_repo_endpoint(repo_id: str) -> dict[str, Any]:
    """Deregister (soft-delete) a repo."""
    result = await deregister_repo(repo_id=repo_id, deregistered_by="api")

    if isinstance(result, Err):
        if result.error == RepoError.NOT_FOUND:
            raise HTTPException(status_code=404, detail=result.message)
        if result.error in (RepoError.HAS_ACTIVE_TRIGGERS, RepoError.ALREADY_DEREGISTERED):
            raise HTTPException(status_code=409, detail=result.message)
        if result.error == RepoError.TRIGGER_CHECK_FAILED:
            raise HTTPException(status_code=503, detail=result.message)
        raise HTTPException(status_code=400, detail=result.message)

    return {"repo_id": repo_id, "status": "deregistered"}


@router.post("/{repo_id}/assign")
async def assign_repo_to_system_endpoint(repo_id: str, body: dict[str, Any]) -> dict[str, Any]:
    """Assign a repo to a system."""
    try:
        result = await assign_repo_to_system(
            repo_id=repo_id,
            system_id=body["system_id"],
        )
    except (KeyError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    if isinstance(result, Err):
        status = 404 if result.error == RepoError.NOT_FOUND else 409
        raise HTTPException(status_code=status, detail=result.message)

    return {"repo_id": repo_id, "system_id": body["system_id"], "status": "assigned"}


@router.post("/{repo_id}/unassign")
async def unassign_repo_from_system_endpoint(repo_id: str) -> dict[str, Any]:
    """Unassign a repo from its system."""
    result = await unassign_repo_from_system(repo_id=repo_id)

    if isinstance(result, Err):
        status = 404 if result.error == RepoError.NOT_FOUND else 409
        raise HTTPException(status_code=status, detail=result.message)

    return {"repo_id": repo_id, "status": "unassigned"}


# ---------------------------------------------------------------------------
# Insight endpoints
# ---------------------------------------------------------------------------


@router.get("/{repo_id}/health")
async def get_repo_health_endpoint(repo_id: str) -> dict[str, Any]:
    """Get health snapshot for a repo."""
    result = await get_repo_health(repo_id)
    if isinstance(result, Err):
        raise HTTPException(status_code=404, detail=result.message)
    return result.value


@router.get("/{repo_id}/cost")
async def get_repo_cost_endpoint(repo_id: str) -> dict[str, Any]:
    """Get cost breakdown for a repo."""
    result = await get_repo_cost(repo_id)
    if isinstance(result, Err):
        raise HTTPException(status_code=404, detail=result.message)
    return result.value


@router.get("/{repo_id}/activity")
async def get_repo_activity_endpoint(
    repo_id: str, offset: int = 0, limit: int = 50
) -> dict[str, Any]:
    """Get execution timeline for a repo."""
    result = await get_repo_activity(repo_id, offset=offset, limit=limit)
    if isinstance(result, Err):
        raise HTTPException(status_code=404, detail=result.message)
    entries = result.value
    return {"entries": entries, "total": len(entries)}


@router.get("/{repo_id}/failures")
async def get_repo_failures_endpoint(repo_id: str, limit: int = 50) -> dict[str, Any]:
    """Get recent failures for a repo."""
    result = await get_repo_failures(repo_id, limit=limit)
    if isinstance(result, Err):
        raise HTTPException(status_code=404, detail=result.message)
    entries = result.value
    return {"failures": entries, "total": len(entries)}


@router.get("/{repo_id}/sessions")
async def get_repo_sessions_endpoint(repo_id: str, limit: int = 50) -> dict[str, Any]:
    """Get agent sessions for a repo."""
    result = await get_repo_sessions(repo_id, limit=limit)
    if isinstance(result, Err):
        raise HTTPException(status_code=404, detail=result.message)
    sessions = result.value
    return {"sessions": sessions, "total": len(sessions)}
