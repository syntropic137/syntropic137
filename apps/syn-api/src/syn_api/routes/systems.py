"""System management API endpoints and service operations.

Provides CRUD for systems with domain aggregate interaction,
plus insight queries (status, cost, activity, patterns, history).
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
    Result,
    SystemErrorCode,
    SystemSummaryResponse,
)

if TYPE_CHECKING:
    from syn_api.auth import AuthContext

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/systems", tags=["systems"])


# =============================================================================
# Service functions (importable by tests)
# =============================================================================


async def create_system(
    organization_id: str,
    name: str,
    description: str = "",
    created_by: str = "",
    auth: AuthContext | None = None,  # noqa: ARG001
) -> Result[str, SystemErrorCode]:
    """Create a new system within an organization."""
    from syn_adapters.storage.repositories import get_system_repository
    from syn_domain.contexts.organization.domain.commands.CreateSystemCommand import (
        CreateSystemCommand,
    )
    from syn_domain.contexts.organization.slices.create_system.CreateSystemHandler import (
        CreateSystemHandler,
    )

    await ensure_connected()

    try:
        command = CreateSystemCommand(
            organization_id=organization_id,
            name=name,
            description=description,
            created_by=created_by,
        )
    except ValueError as e:
        return Err(SystemErrorCode.INVALID_INPUT, message=str(e))

    repo = get_system_repository()
    handler = CreateSystemHandler(repository=repo)

    try:
        aggregate = await handler.handle(command)
        await sync_published_events_to_projections()
        return Ok(aggregate.system_id)
    except Exception as e:
        return Err(SystemErrorCode.INVALID_INPUT, message=str(e))


async def list_systems(
    organization_id: str | None = None,
    auth: AuthContext | None = None,  # noqa: ARG001
) -> Result[list[SystemSummaryResponse], SystemErrorCode]:
    """List systems with optional organization filter."""
    from syn_domain.contexts.organization.slices.list_systems.projection import (
        get_system_projection,
    )

    await ensure_connected()

    projection = get_system_projection()
    systems = await projection.list_all(organization_id=organization_id)

    return Ok(
        [
            SystemSummaryResponse(
                system_id=s.system_id,
                organization_id=s.organization_id,
                name=s.name,
                description=s.description,
                created_by=s.created_by,
                created_at=s.created_at,
                repo_count=s.repo_count,
            )
            for s in systems
        ]
    )


async def get_system(
    system_id: str,
    auth: AuthContext | None = None,  # noqa: ARG001
) -> Result[SystemSummaryResponse, SystemErrorCode]:
    """Get system details."""
    from syn_domain.contexts.organization.slices.list_systems.projection import (
        get_system_projection,
    )

    await ensure_connected()

    projection = get_system_projection()
    system = await projection.get(system_id)

    if system is None:
        return Err(SystemErrorCode.NOT_FOUND, message=f"System {system_id} not found")

    return Ok(
        SystemSummaryResponse(
            system_id=system.system_id,
            organization_id=system.organization_id,
            name=system.name,
            description=system.description,
            created_by=system.created_by,
            created_at=system.created_at,
            repo_count=system.repo_count,
        )
    )


async def update_system(
    system_id: str,
    name: str | None = None,
    description: str | None = None,
    auth: AuthContext | None = None,  # noqa: ARG001
) -> Result[None, SystemErrorCode]:
    """Update a system."""
    from syn_adapters.storage.repositories import get_system_repository
    from syn_domain.contexts.organization.domain.commands.UpdateSystemCommand import (
        UpdateSystemCommand,
    )
    from syn_domain.contexts.organization.slices.manage_system.ManageSystemHandler import (
        ManageSystemHandler,
    )

    await ensure_connected()

    try:
        command = UpdateSystemCommand(
            system_id=system_id,
            name=name,
            description=description,
        )
    except ValueError as e:
        return Err(SystemErrorCode.INVALID_INPUT, message=str(e))

    repo = get_system_repository()
    handler = ManageSystemHandler(repository=repo)
    result = await handler.update(command)

    if result is None:
        return Err(SystemErrorCode.NOT_FOUND, message=f"System {system_id} not found")

    if not result.success:
        error_enum = _classify_sys_error(result.error)
        return Err(error_enum, message=result.error)

    await sync_published_events_to_projections()
    return Ok(None)


async def delete_system(
    system_id: str,
    deleted_by: str = "",
    auth: AuthContext | None = None,  # noqa: ARG001
) -> Result[None, SystemErrorCode]:
    """Soft-delete a system."""
    from syn_adapters.storage.repositories import get_system_repository
    from syn_domain.contexts.organization.domain.commands.DeleteSystemCommand import (
        DeleteSystemCommand,
    )
    from syn_domain.contexts.organization.slices.manage_system.ManageSystemHandler import (
        ManageSystemHandler,
    )

    await ensure_connected()

    try:
        command = DeleteSystemCommand(
            system_id=system_id,
            deleted_by=deleted_by,
        )
    except ValueError as e:
        return Err(SystemErrorCode.INVALID_INPUT, message=str(e))

    repo = get_system_repository()
    handler = ManageSystemHandler(repository=repo)
    result = await handler.delete(command)

    if result is None:
        return Err(SystemErrorCode.NOT_FOUND, message=f"System {system_id} not found")

    if not result.success:
        error_enum = _classify_sys_error(result.error)
        return Err(error_enum, message=result.error)

    await sync_published_events_to_projections()
    return Ok(None)


# ---------------------------------------------------------------------------
# Insight queries — system-level status, cost, activity, patterns, history
# ---------------------------------------------------------------------------


async def get_system_status(system_id: str) -> Result[dict[str, Any], SystemErrorCode]:
    """Get cross-repo health overview for a system."""
    from syn_adapters.projection_stores import get_projection_store
    from syn_domain.contexts.organization.domain.queries.get_system_status import (
        GetSystemStatusQuery,
    )
    from syn_domain.contexts.organization.slices.list_repos.projection import (
        get_repo_projection,
    )
    from syn_domain.contexts.organization.slices.list_systems.projection import (
        get_system_projection,
    )
    from syn_domain.contexts.organization.slices.system_status.GetSystemStatusHandler import (
        GetSystemStatusHandler,
    )

    await ensure_connected()

    sys_proj = get_system_projection()
    if (await sys_proj.get(system_id)) is None:
        return Err(SystemErrorCode.NOT_FOUND, message=f"System {system_id} not found")

    handler = GetSystemStatusHandler(
        store=get_projection_store(),
        system_projection=sys_proj,
        repo_projection=get_repo_projection(),
    )
    result = await handler.handle(GetSystemStatusQuery(system_id=system_id))
    return Ok(result.to_dict())


async def get_system_cost(system_id: str) -> Result[dict[str, Any], SystemErrorCode]:
    """Get cost breakdown for a system."""
    from syn_adapters.projection_stores import get_projection_store
    from syn_domain.contexts.organization.domain.queries.get_system_cost import (
        GetSystemCostQuery,
    )
    from syn_domain.contexts.organization.slices.list_repos.projection import (
        get_repo_projection,
    )
    from syn_domain.contexts.organization.slices.list_systems.projection import (
        get_system_projection,
    )
    from syn_domain.contexts.organization.slices.system_cost.GetSystemCostHandler import (
        GetSystemCostHandler,
    )

    await ensure_connected()

    sys_proj = get_system_projection()
    if (await sys_proj.get(system_id)) is None:
        return Err(SystemErrorCode.NOT_FOUND, message=f"System {system_id} not found")

    handler = GetSystemCostHandler(
        store=get_projection_store(),
        system_projection=sys_proj,
        repo_projection=get_repo_projection(),
    )
    result = await handler.handle(GetSystemCostQuery(system_id=system_id))
    return Ok(result.to_dict())


async def get_system_activity(
    system_id: str, offset: int = 0, limit: int = 50
) -> Result[list[dict[str, Any]], SystemErrorCode]:
    """Get execution timeline for a system."""
    from syn_adapters.projection_stores import get_projection_store
    from syn_domain.contexts.organization.domain.queries.get_system_activity import (
        GetSystemActivityQuery,
    )
    from syn_domain.contexts.organization.slices.list_repos.projection import (
        get_repo_projection,
    )
    from syn_domain.contexts.organization.slices.list_systems.projection import (
        get_system_projection,
    )
    from syn_domain.contexts.organization.slices.system_activity.GetSystemActivityHandler import (
        GetSystemActivityHandler,
    )

    await ensure_connected()

    _sys_proj = get_system_projection()
    if (await _sys_proj.get(system_id)) is None:
        return Err(SystemErrorCode.NOT_FOUND, message=f"System {system_id} not found")

    handler = GetSystemActivityHandler(
        store=get_projection_store(),
        repo_projection=get_repo_projection(),
    )
    entries = await handler.handle(
        GetSystemActivityQuery(system_id=system_id, offset=offset, limit=limit)
    )
    return Ok([e.to_dict() for e in entries])


async def get_system_patterns(
    system_id: str,
) -> Result[dict[str, Any], SystemErrorCode]:
    """Get recurring failure and cost patterns for a system."""
    from syn_adapters.projection_stores import get_projection_store
    from syn_domain.contexts.organization.domain.queries.get_system_patterns import (
        GetSystemPatternsQuery,
    )
    from syn_domain.contexts.organization.slices.list_repos.projection import (
        get_repo_projection,
    )
    from syn_domain.contexts.organization.slices.list_systems.projection import (
        get_system_projection,
    )
    from syn_domain.contexts.organization.slices.system_patterns.GetSystemPatternsHandler import (
        GetSystemPatternsHandler,
    )

    await ensure_connected()

    sys_proj = get_system_projection()
    if (await sys_proj.get(system_id)) is None:
        return Err(SystemErrorCode.NOT_FOUND, message=f"System {system_id} not found")

    handler = GetSystemPatternsHandler(
        store=get_projection_store(),
        system_projection=sys_proj,
        repo_projection=get_repo_projection(),
    )
    result = await handler.handle(GetSystemPatternsQuery(system_id=system_id))
    return Ok(result.to_dict())


async def get_system_history(
    system_id: str, offset: int = 0, limit: int = 50
) -> Result[list[dict[str, Any]], SystemErrorCode]:
    """Get historical execution timeline for a system."""
    from syn_adapters.projection_stores import get_projection_store
    from syn_domain.contexts.organization.domain.queries.get_system_history import (
        GetSystemHistoryQuery,
    )
    from syn_domain.contexts.organization.slices.list_repos.projection import (
        get_repo_projection,
    )
    from syn_domain.contexts.organization.slices.list_systems.projection import (
        get_system_projection,
    )
    from syn_domain.contexts.organization.slices.system_history.GetSystemHistoryHandler import (
        GetSystemHistoryHandler,
    )

    await ensure_connected()

    _sys_proj = get_system_projection()
    if (await _sys_proj.get(system_id)) is None:
        return Err(SystemErrorCode.NOT_FOUND, message=f"System {system_id} not found")

    handler = GetSystemHistoryHandler(
        store=get_projection_store(),
        repo_projection=get_repo_projection(),
    )
    entries = await handler.handle(
        GetSystemHistoryQuery(system_id=system_id, offset=offset, limit=limit)
    )
    return Ok([e.to_dict() for e in entries])


def _classify_sys_error(error_msg: str) -> SystemErrorCode:
    """Map a domain ValueError message to a specific SystemErrorCode."""
    lower = error_msg.lower()
    if "already deleted" in lower:
        return SystemErrorCode.ALREADY_DELETED
    if "has repos" in lower:
        return SystemErrorCode.HAS_REPOS
    return SystemErrorCode.INVALID_INPUT


# =============================================================================
# HTTP Endpoints
# =============================================================================


@router.post("")
async def create_system_endpoint(body: dict[str, Any]) -> dict[str, Any]:
    """Create a new system."""
    try:
        result = await create_system(
            organization_id=body["organization_id"],
            name=body["name"],
            description=body.get("description", ""),
            created_by=body.get("created_by", "api"),
        )
    except (KeyError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    if isinstance(result, Err):
        raise HTTPException(status_code=400, detail=result.message)

    return {"system_id": result.value, "name": body["name"]}


@router.get("")
async def list_systems_endpoint(organization_id: str | None = None) -> dict[str, Any]:
    """List systems with optional organization filter."""
    result = await list_systems(organization_id=organization_id)

    if isinstance(result, Err):
        raise HTTPException(status_code=500, detail=result.message)

    return {
        "systems": [s.model_dump() for s in result.value],
        "total": len(result.value),
    }


@router.get("/{system_id}")
async def get_system_endpoint(system_id: str) -> SystemSummaryResponse:
    """Get system details."""
    result = await get_system(system_id)

    if isinstance(result, Err):
        raise HTTPException(status_code=404, detail=result.message)

    return result.value


@router.put("/{system_id}")
async def update_system_endpoint(system_id: str, body: dict[str, Any]) -> dict[str, Any]:
    """Update a system."""
    result = await update_system(
        system_id=system_id,
        name=body.get("name"),
        description=body.get("description"),
    )

    if isinstance(result, Err):
        status = 404 if result.error == SystemErrorCode.NOT_FOUND else 400
        raise HTTPException(status_code=status, detail=result.message)

    return {"system_id": system_id, "status": "updated"}


@router.delete("/{system_id}")
async def delete_system_endpoint(system_id: str) -> dict[str, Any]:
    """Soft-delete a system."""
    result = await delete_system(
        system_id=system_id,
        deleted_by="api",
    )

    if isinstance(result, Err):
        status = 404 if result.error == SystemErrorCode.NOT_FOUND else 409
        raise HTTPException(status_code=status, detail=result.message)

    return {"system_id": system_id, "status": "deleted"}


# ---------------------------------------------------------------------------
# Insight endpoints
# ---------------------------------------------------------------------------


@router.get("/{system_id}/status")
async def get_system_status_endpoint(system_id: str) -> dict[str, Any]:
    """Get cross-repo health overview for a system."""
    result = await get_system_status(system_id)
    if isinstance(result, Err):
        raise HTTPException(status_code=404, detail=result.message)
    return result.value


@router.get("/{system_id}/cost")
async def get_system_cost_endpoint(system_id: str) -> dict[str, Any]:
    """Get cost breakdown for a system."""
    result = await get_system_cost(system_id)
    if isinstance(result, Err):
        raise HTTPException(status_code=404, detail=result.message)
    return result.value


@router.get("/{system_id}/activity")
async def get_system_activity_endpoint(
    system_id: str, offset: int = 0, limit: int = 50
) -> dict[str, Any]:
    """Get execution timeline for a system."""
    result = await get_system_activity(system_id, offset=offset, limit=limit)
    if isinstance(result, Err):
        raise HTTPException(status_code=404, detail=result.message)
    return {"entries": result.value, "total": len(result.value)}


@router.get("/{system_id}/patterns")
async def get_system_patterns_endpoint(system_id: str) -> dict[str, Any]:
    """Get recurring failure and cost patterns for a system."""
    result = await get_system_patterns(system_id)
    if isinstance(result, Err):
        raise HTTPException(status_code=404, detail=result.message)
    return result.value


@router.get("/{system_id}/history")
async def get_system_history_endpoint(
    system_id: str, offset: int = 0, limit: int = 50
) -> dict[str, Any]:
    """Get historical execution timeline for a system."""
    result = await get_system_history(system_id, offset=offset, limit=limit)
    if isinstance(result, Err):
        raise HTTPException(status_code=404, detail=result.message)
    return {"entries": result.value, "total": len(result.value)}
