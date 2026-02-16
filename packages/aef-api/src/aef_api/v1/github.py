"""GitHub operations — repositories and installations.

Installation and repository listing stubs. Trigger operations have
moved to ``aef_api.v1.triggers``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from aef_api.types import Err, GitHubError, Result

if TYPE_CHECKING:
    from aef_api.auth import AuthContext


async def list_repos(
    installation_id: str | None = None,
    limit: int = 100,
    offset: int = 0,
    auth: AuthContext | None = None,
) -> Result[list[dict[str, Any]], GitHubError]:
    """List GitHub repositories accessible via the GitHub App.

    Args:
        installation_id: Optional filter by installation ID.
        limit: Maximum results to return.
        offset: Pagination offset.
        auth: Optional authentication context.

    Returns:
        Ok(list[dict]) on success, Err(GitHubError) on failure.
    """
    # TODO(#92): Implement — maps to domain slice github/list_repos
    return Err(
        GitHubError.NOT_IMPLEMENTED,
        message="list_repos not yet implemented",
    )


async def get_installation(
    installation_id: str,
    auth: AuthContext | None = None,
) -> Result[dict[str, Any], GitHubError]:
    """Get details about a GitHub App installation.

    Args:
        installation_id: The installation ID to look up.
        auth: Optional authentication context.

    Returns:
        Ok(dict) on success, Err(GitHubError) on failure.
    """
    # TODO(#92): Implement — maps to domain slice github/get_installation
    return Err(
        GitHubError.NOT_IMPLEMENTED,
        message="get_installation not yet implemented",
    )
