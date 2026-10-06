"""GitHub App query routes.

Exposes query endpoints for GitHub App data (accessible repos, installations).
These answer from the GitHub API, not projections; the all-installations
listing is cached briefly (see ``github_repo_listing_cache``).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from syn_domain.contexts.github.slices.get_installation.projection import (
        InstallationProjection,
    )

from fastapi import APIRouter, HTTPException

from syn_api._wiring import ensure_connected
from syn_api.services.github_repo_listing_cache import (
    CachedRepoListing,
    RepoListingCache,
    get_repo_listing_cache,
)
from syn_api.types import (
    Err,
    GitHubError,
    GitHubRepoListResponse,
    GitHubRepoLookup,
    GitHubRepoResponse,
    Ok,
    Result,
)


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
) -> Result[GitHubRepoListResponse, GitHubError]:
    """List repositories accessible to the GitHub App (live query).

    Args:
        installation_id: Filter to a specific installation. If None, queries
            all active installations and aggregates results.
        include_private: Whether to include private repositories.
        auth: Authentication context (reserved for future use).

    Returns:
        Ok with the listing and how complete it is, or Err with error details.
        A GitHub failure for one installation is reported in ``lookup``, not
        hidden as an installation with no repos.
    """
    from syn_adapters.github.client import (
        GitHubAppError,
        GitHubAuthError,
        GitHubRateLimitError,
        get_github_client,
    )

    await ensure_connected()

    try:
        repos, lookup = await _fetch_repos(get_github_client(), installation_id, include_private)
        return Ok(
            GitHubRepoListResponse(
                repos=repos,
                total=len(repos),
                installation_id=installation_id,
                lookup=lookup,
            )
        )
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
) -> tuple[list[GitHubRepoResponse], GitHubRepoLookup]:
    """Dispatch to single-installation or aggregate query."""
    if installation_id:
        # A failure here propagates: the caller asked about this one installation.
        raw_repos = await client.list_accessible_repos(installation_id=installation_id)
        return _build_repo_list(raw_repos, installation_id, include_private), (
            GitHubRepoLookup.COMPLETE
        )
    return await _aggregate_all_installations(client, include_private)


async def _sync_installations(
    client: _RepoLister,
    projection: InstallationProjection,
) -> tuple[list, bool] | None:
    """Fetch all installations from GitHub API and upsert into the projection.

    Returns the refreshed installation list (may be empty if no installations
    exist) and whether it holds every installation GitHub returned; one that
    failed to persist is missing from it. Returns None if the GitHub API call
    itself failed so the caller can distinguish a successful empty result from
    a network failure.
    """
    try:
        raw = await client.list_installations()
    except Exception:
        logger.warning("GitHub API installation sync failed", exc_info=True)
        return None
    result = []
    for item in raw:
        try:
            result.append(await projection.upsert_from_github_api(item))
        except Exception:
            logger.warning("Failed to upsert installation %s", item.get("id"), exc_info=True)
    logger.info("Synced %d of %d installation(s) from GitHub API", len(result), len(raw))
    return result, len(result) == len(raw)


async def _repos_for_installation(
    client: _RepoLister,
    installation_id: str,
) -> list[GitHubRepoResponse] | None:
    """Fetch every repo one installation reaches, private ones included.

    Returns None if GitHub could not be asked, so the caller can tell a failed
    lookup apart from an installation that reaches no repos.
    """
    try:
        raw_repos = await client.list_accessible_repos(installation_id=installation_id)
    except Exception:
        logger.warning(
            "Failed to list repos for installation %s, skipping",
            installation_id,
            exc_info=True,
        )
        return None
    return _build_repo_list(raw_repos, installation_id, include_private=True)


async def _aggregate_all_installations(
    client: _RepoLister,
    include_private: bool,
) -> tuple[list[GitHubRepoResponse], GitHubRepoLookup]:
    """Return the repos every installation reaches, from the cache when it can.

    A listing younger than ``FRESH_FOR`` is served as complete without asking
    GitHub. An older one is served at once as ``partial``, since a repo added
    since would be missing from it, while a refresh runs in the background. With
    nothing cached GitHub is asked live, as before the cache existed.
    """
    cache = get_repo_listing_cache()
    cached = await cache.get()
    if cached is None:
        repos, lookup = await _ask_github(client, cache)
    elif cached.is_fresh():
        repos, lookup = cached.repos, GitHubRepoLookup.COMPLETE
    else:
        _revalidate_in_background(client, cache)
        repos, lookup = cached.repos, GitHubRepoLookup.PARTIAL
    if not include_private:
        repos = [r for r in repos if not r.private]
    return repos, lookup


_revalidation: asyncio.Task[object] | None = None


def _revalidate_in_background(client: _RepoLister, cache: RepoListingCache) -> None:
    """Start refreshing the cache unless this process already is."""
    global _revalidation
    if _revalidation is not None and not _revalidation.done():
        return
    _revalidation = asyncio.create_task(_ask_github(client, cache))
    _revalidation.add_done_callback(_log_revalidation_failure)


def _log_revalidation_failure(task: asyncio.Task[object]) -> None:
    if not task.cancelled() and task.exception() is not None:
        logger.warning("GitHub repo listing refresh failed", exc_info=task.exception())


async def _ask_github(
    client: _RepoLister,
    cache: RepoListingCache,
) -> tuple[list[GitHubRepoResponse], GitHubRepoLookup]:
    """Ask GitHub for every installation's repos, and cache a complete answer.

    Installations are asked concurrently. A listing that is not complete is
    returned but never cached, so the cache only ever holds what GitHub
    confirmed in full.
    """
    from syn_domain.contexts.github.slices.get_installation.projection import (
        get_installation_projection,
    )

    started_at = datetime.now(UTC)
    installations, installations_current = await _known_installations(
        client, get_installation_projection()
    )
    answers = await asyncio.gather(
        *(_repos_for_installation(client, inst.installation_id) for inst in installations)
    )
    seen_ids: set[int] = set()
    repos: list[GitHubRepoResponse] = []
    for found in answers:
        for repo in found or []:
            if repo.github_id not in seen_ids:
                seen_ids.add(repo.github_id)
                repos.append(repo)
    answered = sum(found is not None for found in answers)
    lookup = _lookup_of(len(installations), answered, installations_current)
    if lookup == GitHubRepoLookup.COMPLETE:
        # Aged from when GitHub was asked, not when it finished answering.
        await cache.put(CachedRepoListing(repos=repos, fetched_at=started_at))
    return repos, lookup


async def _known_installations(
    client: _RepoLister,
    projection: InstallationProjection,
) -> tuple[list, bool]:
    """Return the installations to query and whether that list is current.

    Asks GitHub every time: a cached list, however recent, cannot know about an
    installation added since, and the listing is labelled complete on the
    strength of this answer. If GitHub cannot be asked, the cached list is used
    but is not current; nor is a refreshed list when an installation failed to
    persist.
    """
    refreshed = await _sync_installations(client, projection)
    if refreshed is None:
        return await projection.get_all_active(), False
    return refreshed


def _lookup_of(asked: int, answered: int, installations_current: bool) -> GitHubRepoLookup:
    """How much of the App's access a listing covers.

    Complete only when the installation list is current and every installation
    answered; nothing answered and nothing confirmed is unavailable.
    """
    if answered == asked and installations_current:
        return GitHubRepoLookup.COMPLETE
    if answered == 0:
        return GitHubRepoLookup.UNAVAILABLE
    return GitHubRepoLookup.PARTIAL


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

    With no installation_id, aggregates every installation. The last complete
    listing is cached: under a minute old it is served as ``complete``; older,
    it is served as ``partial`` while a background refresh asks GitHub; with
    none cached, GitHub is asked live. The GitHub App's ``installation`` and
    ``installation_repositories`` webhooks drop the cache at once. A single
    installation_id is always asked live.

    ``lookup`` says whether a repo missing from ``repos`` is known to be out of
    the App's reach (``complete``) or merely went unseen because GitHub failed.
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

    return result.value
