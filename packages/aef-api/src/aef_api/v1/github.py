"""GitHub operations — repositories, installations, and triggers.

Maps to the github context in aef-domain.

Stub implementation for Phase 1 — complete signatures and types,
with TODO markers pointing to domain slices.
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
    # Wire: GitHub App installation token → list repositories
    return Err(
        GitHubError.NOT_IMPLEMENTED,
        message="list_repos not yet implemented — see #92 Phase 1",
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
    # Wire: GitHub App → get installation details
    return Err(
        GitHubError.NOT_IMPLEMENTED,
        message="get_installation not yet implemented — see #92 Phase 1",
    )


async def register_trigger(
    repo_owner: str,
    repo_name: str,
    event_type: str,
    workflow_id: str,
    config: dict[str, Any] | None = None,
    auth: AuthContext | None = None,
) -> Result[str, GitHubError]:
    """Register a GitHub event trigger for a workflow.

    Args:
        repo_owner: GitHub repository owner.
        repo_name: GitHub repository name.
        event_type: GitHub event type (e.g., "push", "pull_request").
        workflow_id: Workflow to trigger on this event.
        config: Optional trigger configuration (branch filters, etc.).
        auth: Optional authentication context.

    Returns:
        Ok(trigger_id) on success, Err(GitHubError) on failure.
    """
    # TODO(#92): Implement — maps to domain slice github/register_trigger
    # Wire: get_trigger_repository() → TriggerAggregate.register()
    return Err(
        GitHubError.NOT_IMPLEMENTED,
        message="register_trigger not yet implemented — see #92 Phase 1",
    )
