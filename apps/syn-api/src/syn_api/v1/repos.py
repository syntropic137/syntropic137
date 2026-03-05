"""Repo operations — register, manage, and query repos."""

from __future__ import annotations

from typing import TYPE_CHECKING

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
    repos = projection.list_all(
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
    repo = projection.get(repo_id)

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


def _classify_repo_error(error_msg: str) -> RepoError:
    """Map a domain ValueError message to a specific RepoError."""
    lower = error_msg.lower()
    if "already assigned" in lower:
        return RepoError.ALREADY_ASSIGNED
    if "not assigned" in lower:
        return RepoError.NOT_ASSIGNED
    return RepoError.INVALID_INPUT
