"""System operations — create, manage, and query systems."""

from __future__ import annotations

from typing import TYPE_CHECKING

from syn_api._wiring import (
    ensure_connected,
    sync_published_events_to_projections,
)
from syn_api.types import (
    Err,
    Ok,
    Result,
    SystemError,
    SystemSummaryResponse,
)

if TYPE_CHECKING:
    from syn_api.auth import AuthContext


async def create_system(
    organization_id: str,
    name: str,
    description: str = "",
    created_by: str = "",
    auth: AuthContext | None = None,  # noqa: ARG001
) -> Result[str, SystemError]:
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
        return Err(SystemError.INVALID_INPUT, message=str(e))

    repo = get_system_repository()
    handler = CreateSystemHandler(repository=repo)

    try:
        aggregate = await handler.handle(command)
        await sync_published_events_to_projections()
        return Ok(aggregate.system_id)
    except Exception as e:
        return Err(SystemError.INVALID_INPUT, message=str(e))


async def list_systems(
    organization_id: str | None = None,
    auth: AuthContext | None = None,  # noqa: ARG001
) -> Result[list[SystemSummaryResponse], SystemError]:
    """List systems with optional organization filter."""
    from syn_domain.contexts.organization.slices.list_systems.projection import (
        get_system_projection,
    )

    await ensure_connected()

    projection = get_system_projection()
    systems = projection.list_all(organization_id=organization_id)

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
) -> Result[SystemSummaryResponse, SystemError]:
    """Get system details."""
    from syn_domain.contexts.organization.slices.list_systems.projection import (
        get_system_projection,
    )

    await ensure_connected()

    projection = get_system_projection()
    system = projection.get(system_id)

    if system is None:
        return Err(SystemError.NOT_FOUND, message=f"System {system_id} not found")

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
) -> Result[None, SystemError]:
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
        return Err(SystemError.INVALID_INPUT, message=str(e))

    repo = get_system_repository()
    handler = ManageSystemHandler(repository=repo)
    result = await handler.update(command)

    if result is None:
        return Err(SystemError.NOT_FOUND, message=f"System {system_id} not found")

    await sync_published_events_to_projections()
    return Ok(None)


async def delete_system(
    system_id: str,
    deleted_by: str = "",
    auth: AuthContext | None = None,  # noqa: ARG001
) -> Result[None, SystemError]:
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
        return Err(SystemError.INVALID_INPUT, message=str(e))

    repo = get_system_repository()
    handler = ManageSystemHandler(repository=repo)
    result = await handler.delete(command)

    if result is None:
        return Err(
            SystemError.NOT_FOUND, message=f"System {system_id} not found or already deleted"
        )

    await sync_published_events_to_projections()
    return Ok(None)
