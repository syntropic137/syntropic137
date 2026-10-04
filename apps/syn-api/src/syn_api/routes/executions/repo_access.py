"""GitHub App repository access, checked before an execution is accepted (#598).

The execute endpoint calls `_validate_all_repos_access` so a repository the App
cannot reach is a 422 on the request, not a run that fails in its workspace.
"""

from __future__ import annotations

import logging

from fastapi import HTTPException

logger = logging.getLogger(__name__)


def _parse_repo_from_url(repo_url: str | None) -> str | None:
    """Extract owner/repo from a GitHub URL, or None if not applicable."""
    if not repo_url:
        return None
    normalized = repo_url.rstrip("/")
    if "/" not in normalized:
        return None
    parts = normalized.split("/")
    if len(parts) >= 2:
        return f"{parts[-2]}/{parts[-1]}"
    return None


def _build_auth_error_detail(repo_full_name: str, exc: Exception) -> str:
    """Build a user-facing error detail for GitHub App auth failures."""
    exc_message = str(exc)
    if "not installed" in exc_message.lower():
        return (
            f"GitHub App not installed on repository: {repo_full_name}. "
            "Install the GitHub App on this repository before running workflows."
        )
    return f"GitHub App authentication failed for {repo_full_name}: {exc_message}"


async def _validate_all_repos_access(repo_urls: list[str]) -> None:
    """Pre-validate that the GitHub App can access all requested repositories."""
    for url in repo_urls:
        repo_full_name = _parse_repo_from_url(url)
        if repo_full_name:
            await _validate_repo_access(repo_full_name)


async def _validate_repo_access(repo_full_name: str) -> None:
    """Pre-validate that the GitHub App can access the target repository.

    Raises HTTPException(422) if the App is not installed. Logs and
    proceeds on transient errors (network, rate limit).
    """
    from syn_shared.settings.github import GitHubAppSettings

    if not GitHubAppSettings().is_configured:
        return

    from syn_adapters.github.client import GitHubAuthError, get_github_client

    try:
        await get_github_client().get_installation_for_repo(repo_full_name)
    except GitHubAuthError as exc:
        raise HTTPException(
            status_code=422,
            detail=_build_auth_error_detail(repo_full_name, exc),
        ) from exc
    except Exception as exc:
        logger.warning("Could not pre-validate repo access for %s: %s", repo_full_name, exc)
