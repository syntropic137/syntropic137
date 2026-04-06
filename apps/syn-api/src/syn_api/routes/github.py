"""GitHub App query routes.

Exposes live-query endpoints for GitHub App data (accessible repos,
installations). These hit the GitHub API directly — not projections.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Protocol

from fastapi import APIRouter, HTTPException

from syn_api._wiring import ensure_connected
from syn_api.types import (
    Err,
    GitHubError,
    GitHubRepoListResponse,
    GitHubRepoResponse,
    Ok,
    Result,
)

if TYPE_CHECKING:
    from syn_api.auth import AuthContext


class _RepoLister(Protocol):
    """Protocol for listing accessible repos (subset of GitHubAppClient)."""

    async def list_accessible_repos(self, installation_id: str | None = None) -> list[dict]: ...


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/github", tags=["github"])


# =============================================================================
# Service Functions
# =============================================================================


def _map_repo_dict(raw: dict, installation_id: str) -> GitHubRepoResponse | None:
    """Map a raw GitHub API repo dict to a response model.

    Returns None if required fields are missing.
    """
    github_id = raw.get("id")
    name = raw.get("name")
    full_name = raw.get("full_name")

    if github_id is None or name is None or full_name is None:
        logger.warning(
            "Skipping malformed repo entry: %s",
            raw.get("full_name", raw.get("id", "unknown")),
        )
        return None

    owner = str(full_name).split("/")[0] if "/" in str(full_name) else ""

    return GitHubRepoResponse(
        github_id=int(github_id),
        name=str(name),
        full_name=str(full_name),
        private=bool(raw.get("private", False)),
        default_branch=str(raw.get("default_branch", "main")),
        owner=owner,
        installation_id=installation_id,
    )


async def list_accessible_repos(
    installation_id: str | None = None,
    include_private: bool = True,
    auth: AuthContext | None = None,
) -> Result[list[GitHubRepoResponse], GitHubError]:
    """List repositories accessible to the GitHub App (live query).

    Args:
        installation_id: Filter to a specific installation. If None, queries
            all active installations and aggregates results.
        include_private: Whether to include private repositories.
        auth: Authentication context (reserved for future use).

    Returns:
        Ok with list of GitHubRepoResponse, or Err with error details.
    """
    from syn_adapters.github.client import (
        GitHubAppError,
        GitHubAuthError,
        GitHubRateLimitError,
        get_github_client,
    )

    await ensure_connected()

    try:
        repos = await _fetch_repos(get_github_client(), installation_id, include_private)
        return Ok(repos)
    except GitHubAuthError as e:
        return Err(GitHubError.AUTH_REQUIRED, message=str(e))
    except GitHubRateLimitError as e:
        return Err(GitHubError.RATE_LIMITED, message=str(e))
    except GitHubAppError as e:
        return Err(GitHubError.PROCESSING_FAILED, message=str(e))


async def _fetch_repos(
    client: _RepoLister,
    installation_id: str | None,
    include_private: bool,
) -> list[GitHubRepoResponse]:
    """Dispatch to single-installation or aggregate query."""
    if installation_id:
        raw_repos = await client.list_accessible_repos(installation_id=installation_id)
        return _build_repo_list(raw_repos, installation_id, include_private)
    return await _aggregate_all_installations(client, include_private)


async def _aggregate_all_installations(
    client: _RepoLister,
    include_private: bool,
) -> list[GitHubRepoResponse]:
    """Query all active installations and return deduplicated repos."""
    from syn_domain.contexts.github.slices.get_installation.projection import (
        get_installation_projection,
    )

    projection = get_installation_projection()
    installations = await projection.get_all_active()

    if not installations:
        return []

    seen_ids: set[int] = set()
    repos: list[GitHubRepoResponse] = []

    for inst in installations:
        try:
            raw_repos = await client.list_accessible_repos(installation_id=inst.installation_id)
        except Exception:
            logger.warning(
                "Failed to list repos for installation %s, skipping",
                inst.installation_id,
                exc_info=True,
            )
            continue

        for repo in _build_repo_list(raw_repos, inst.installation_id, include_private):
            if repo.github_id not in seen_ids:
                seen_ids.add(repo.github_id)
                repos.append(repo)

    return repos


def _build_repo_list(
    raw_repos: list[dict],
    installation_id: str,
    include_private: bool,
) -> list[GitHubRepoResponse]:
    """Map and filter raw GitHub repo dicts to response models."""
    repos: list[GitHubRepoResponse] = []
    for raw in raw_repos:
        repo = _map_repo_dict(raw, installation_id)
        if repo is None:
            continue
        if not include_private and repo.private:
            continue
        repos.append(repo)
    return repos


# =============================================================================
# HTTP Endpoints
# =============================================================================


@router.get("/repos")
async def list_accessible_repos_endpoint(
    installation_id: str | None = None,
    include_private: bool = True,
) -> GitHubRepoListResponse:
    """List repositories accessible to the GitHub App.

    Makes a live query to the GitHub API. If no installation_id is provided,
    queries all active installations and aggregates the results.
    """
    result = await list_accessible_repos(
        installation_id=installation_id,
        include_private=include_private,
    )

    if isinstance(result, Err):
        status_map: dict[GitHubError, int] = {
            GitHubError.NOT_FOUND: 404,
            GitHubError.AUTH_REQUIRED: 401,
            GitHubError.RATE_LIMITED: 429,
        }
        status = status_map.get(result.error, 502)
        raise HTTPException(status_code=status, detail=result.message)

    return GitHubRepoListResponse(
        repos=result.value,
        total=len(result.value),
        installation_id=installation_id,
    )
