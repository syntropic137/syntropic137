"""Service functions for querying GitHub App installations and repositories."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from syn_api._wiring import ensure_connected
from syn_api.types import Err, GitHubError, Ok, Result

if TYPE_CHECKING:
    from collections.abc import Sequence

    from syn_domain.contexts.github.slices.get_installation.projection import (
        InstallationProjection,
    )

logger = logging.getLogger(__name__)


async def _get_repos_for_installation(
    projection: InstallationProjection, installation_id: str
) -> Result[list[str], GitHubError]:
    """Get repositories for a specific installation."""
    inst = await projection.get(installation_id)
    if inst is None:
        return Err(
            GitHubError.NOT_FOUND,
            message=f"Installation {installation_id} not found",
        )
    repos = inst.repositories if hasattr(inst, "repositories") else []
    return Ok(repos)


async def _collect_all_repos(projection: InstallationProjection) -> list[str]:
    """Collect all repositories from all active installations."""
    active = await projection.get_all_active()
    repos: list[str] = []
    for inst in active:
        repos.extend(inst.repositories)
    return repos


def _normalize_repos(repos: Sequence[str | dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalize repo entries to dict format."""
    return [{"full_name": r} if isinstance(r, str) else r for r in repos]


async def list_repos(
    installation_id: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> Result[list[dict[str, Any]], GitHubError]:
    """List GitHub repositories accessible via the GitHub App."""
    await ensure_connected()
    try:
        from syn_domain.contexts.github.slices.get_installation.projection import (
            get_installation_projection,
        )

        projection = get_installation_projection()

        if installation_id:
            result = await _get_repos_for_installation(projection, installation_id)
            if isinstance(result, Err):
                return result
            repos = result.value
        else:
            repos = await _collect_all_repos(projection)

        page = repos[offset : offset + limit]
        return Ok(_normalize_repos(page))
    except Exception as e:
        return Err(GitHubError.NOT_FOUND, message=str(e))


async def get_installation(
    installation_id: str,
) -> Result[dict[str, Any], GitHubError]:
    """Get details about a GitHub App installation."""
    await ensure_connected()
    try:
        from syn_domain.contexts.github.slices.get_installation.projection import (
            get_installation_projection,
        )

        projection = get_installation_projection()
        inst = await projection.get(installation_id)

        if inst is None:
            return Err(
                GitHubError.NOT_FOUND,
                message=f"Installation {installation_id} not found",
            )

        return Ok(
            {
                "installation_id": installation_id,
                "account": inst.account_name,
                "status": inst.status,
                "repositories": inst.repositories,
                "created_at": str(inst.installed_at or ""),
            }
        )
    except Exception as e:
        return Err(GitHubError.NOT_FOUND, message=str(e))
