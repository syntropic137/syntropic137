"""GitHub App query routes.

Exposes live-query endpoints for GitHub App data (accessible repos,
installations). These hit the GitHub API directly — not projections.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from syn_domain.contexts.github.slices.get_installation.projection import (
        InstallationProjection,
    )

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

_INSTALLATION_SYNC_TTL = timedelta(hours=1)


class _RepoLister(Protocol):
    """Protocol for listing repos and installations (subset of GitHubAppClient)."""

    async def list_accessible_repos(self, installation_id: str | None = None) -> list[dict]: ...
    async def list_installations(self) -> list[dict]: ...


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


def _is_stale(installations: list) -> bool:
    """Return True if the installation cache is empty or any record is past the TTL."""
    if not installations:
        return True
    now = datetime.now(UTC)
    return any(
        inst.synced_at is None or (now - inst.synced_at) > _INSTALLATION_SYNC_TTL
        for inst in installations
    )


async def _sync_installations(
    client: _RepoLister,
    projection: InstallationProjection,
) -> list:
    """Fetch all installations from GitHub API and upsert into the projection.

    Called when the installation cache is empty or stale. Returns the refreshed
    installation list, or an empty list if the GitHub API call fails.
    """
    try:
        raw = await client.list_installations()
    except Exception:
        logger.warning("GitHub API installation sync failed", exc_info=True)
        return []
    result = []
    for item in raw:
        try:
            result.append(await projection.upsert_from_github_api(item))
        except Exception:
            logger.warning("Failed to upsert installation %s", item.get("id"), exc_info=True)
    logger.info("Synced %d installation(s) from GitHub API", len(result))
    return result


async def _repos_for_installation(
    client: _RepoLister,
    installation_id: str,
    seen_ids: set[int],
    include_private: bool,
) -> list[GitHubRepoResponse]:
    """Fetch repos for one installation, skipping IDs already in seen_ids."""
    try:
        raw_repos = await client.list_accessible_repos(installation_id=installation_id)
    except Exception:
        logger.warning(
            "Failed to list repos for installation %s, skipping",
            installation_id,
            exc_info=True,
        )
        return []
    result: list[GitHubRepoResponse] = []
    for repo in _build_repo_list(raw_repos, installation_id, include_private):
        if repo.github_id not in seen_ids:
            seen_ids.add(repo.github_id)
            result.append(repo)
    return result


async def _aggregate_all_installations(
    client: _RepoLister,
    include_private: bool,
) -> list[GitHubRepoResponse]:
    """Query all active installations and return deduplicated repos.

    Refreshes the installation cache from GitHub if it is empty or older than
    the TTL, so the endpoint works without a webhook configured.
    """
    from syn_domain.contexts.github.slices.get_installation.projection import (
        get_installation_projection,
    )

    projection = get_installation_projection()
    installations = await projection.get_all_active()

    if _is_stale(installations):
        refreshed = await _sync_installations(client, projection)
        if refreshed or not installations:
            installations = refreshed

    if not installations:
        return []

    seen_ids: set[int] = set()
    repos: list[GitHubRepoResponse] = []
    for inst in installations:
        repos.extend(
            await _repos_for_installation(client, inst.installation_id, seen_ids, include_private)
        )
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

    Queries all active installations and aggregates results when no
    installation_id is provided. The installation list is cached locally with
    a 1-hour TTL: if empty or stale, it bootstraps automatically from the
    GitHub API without requiring a webhook URL. Stale data is kept as a
    fallback if the GitHub API is unreachable during refresh.
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
