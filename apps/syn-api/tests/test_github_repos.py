"""Tests for GET /github/repos endpoint and service function."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from syn_api.routes import github as github_routes
from syn_api.routes.github import list_accessible_repos
from syn_api.services.github_repo_listing_cache import reset_repo_listing_cache
from syn_api.types import (
    Err,
    GitHubError,
    GitHubRepoListResponse,
    GitHubRepoLookup,
    Ok,
    Result,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _no_cached_listing() -> Iterator[None]:
    reset_repo_listing_cache()
    with (
        patch.object(github_routes, "_revalidation", None),
        patch.object(github_routes, "_revalidation_generation", None),
    ):
        yield


async def _aggregate() -> Result[GitHubRepoListResponse, GitHubError]:
    """Load the page with no listing cached, then return what the refresh it starts found."""
    served = await list_accessible_repos(installation_id=None)
    assert isinstance(served, Ok)
    assert served.value.lookup == GitHubRepoLookup.UNAVAILABLE
    task = github_routes._revalidation
    assert task is not None
    repos, lookup = await task
    return Ok(GitHubRepoListResponse(repos=repos, total=len(repos), lookup=lookup))


def _make_repo(idx: int, *, private: bool = False) -> dict:
    """Create a raw GitHub API repo dict."""
    return {
        "id": idx,
        "name": f"repo-{idx}",
        "full_name": f"org/repo-{idx}",
        "private": private,
        "default_branch": "main",
    }


def _make_installation(installation_id: str) -> MagicMock:
    """Create a mock Installation read model with a fresh synced_at."""
    inst = MagicMock()
    inst.installation_id = installation_id
    inst.synced_at = datetime.now(UTC) - timedelta(minutes=5)
    return inst


@pytest.mark.asyncio
async def test_single_installation() -> None:
    """Service returns repos for a specific installation."""
    raw_repos = [_make_repo(1), _make_repo(2, private=True)]

    mock_client = MagicMock()
    mock_client.list_accessible_repos = AsyncMock(return_value=raw_repos)

    with (
        patch("syn_api.routes.github.ensure_connected", new_callable=AsyncMock) as mock_ensure,
        patch(
            "syn_adapters.github.client.get_github_client",
            return_value=mock_client,
        ),
    ):
        result = await list_accessible_repos(installation_id="inst-1")
        mock_ensure.assert_awaited_once()

    assert isinstance(result, Ok)
    assert len(result.value.repos) == 2
    assert result.value.repos[0].github_id == 1
    assert result.value.repos[0].full_name == "org/repo-1"
    assert result.value.repos[0].owner == "org"
    assert result.value.repos[0].installation_id == "inst-1"


@pytest.mark.asyncio
async def test_all_installations_aggregated() -> None:
    """Without installation_id, aggregates from all active installations."""
    inst1_repos = [_make_repo(1), _make_repo(2)]
    inst2_repos = [_make_repo(2), _make_repo(3)]  # repo-2 is a duplicate

    mock_client = MagicMock()
    mock_client.list_accessible_repos = AsyncMock(side_effect=[inst1_repos, inst2_repos])

    mock_projection = MagicMock()
    mock_projection.get_all_active = AsyncMock(
        return_value=[
            _make_installation("inst-1"),
            _make_installation("inst-2"),
        ]
    )

    with (
        patch("syn_api.routes.github.ensure_connected", new_callable=AsyncMock) as mock_ensure,
        patch(
            "syn_adapters.github.client.get_github_client",
            return_value=mock_client,
        ),
        patch(
            "syn_domain.contexts.github.slices.get_installation.projection.get_installation_projection",
            return_value=mock_projection,
        ),
    ):
        result = await _aggregate()
        mock_ensure.assert_awaited_once()

    assert isinstance(result, Ok)
    # Repo 2 appears in both installations — should be deduplicated
    assert len(result.value.repos) == 3
    github_ids = {r.github_id for r in result.value.repos}
    assert github_ids == {1, 2, 3}


@pytest.mark.asyncio
async def test_auth_error_maps_to_err() -> None:
    """GitHubAuthError maps to Err(AUTH_REQUIRED)."""
    from syn_adapters.github.client import GitHubAuthError

    mock_client = MagicMock()
    mock_client.list_accessible_repos = AsyncMock(side_effect=GitHubAuthError("bad token"))

    with (
        patch("syn_api.routes.github.ensure_connected", new_callable=AsyncMock) as mock_ensure,
        patch(
            "syn_adapters.github.client.get_github_client",
            return_value=mock_client,
        ),
    ):
        result = await list_accessible_repos(installation_id="inst-1")
        mock_ensure.assert_awaited_once()

    assert isinstance(result, Err)
    assert result.error == GitHubError.AUTH_REQUIRED


@pytest.mark.asyncio
async def test_rate_limit_maps_to_err() -> None:
    """GitHubRateLimitError maps to Err(RATE_LIMITED)."""
    from syn_adapters.github.client import GitHubRateLimitError

    mock_client = MagicMock()
    mock_client.list_accessible_repos = AsyncMock(side_effect=GitHubRateLimitError("rate limited"))

    with (
        patch("syn_api.routes.github.ensure_connected", new_callable=AsyncMock) as mock_ensure,
        patch(
            "syn_adapters.github.client.get_github_client",
            return_value=mock_client,
        ),
    ):
        result = await list_accessible_repos(installation_id="inst-1")
        mock_ensure.assert_awaited_once()

    assert isinstance(result, Err)
    assert result.error == GitHubError.RATE_LIMITED


@pytest.mark.asyncio
async def test_include_private_false_filters() -> None:
    """include_private=False filters out private repos."""
    raw_repos = [_make_repo(1), _make_repo(2, private=True), _make_repo(3)]

    mock_client = MagicMock()
    mock_client.list_accessible_repos = AsyncMock(return_value=raw_repos)

    with (
        patch("syn_api.routes.github.ensure_connected", new_callable=AsyncMock) as mock_ensure,
        patch(
            "syn_adapters.github.client.get_github_client",
            return_value=mock_client,
        ),
    ):
        result = await list_accessible_repos(installation_id="inst-1", include_private=False)
        mock_ensure.assert_awaited_once()

    assert isinstance(result, Ok)
    assert len(result.value.repos) == 2
    assert all(not r.private for r in result.value.repos)


def _make_installation_with_synced_at(synced_at: datetime | None) -> MagicMock:
    inst = MagicMock()
    inst.synced_at = synced_at
    return inst


# =============================================================================
# _aggregate_all_installations — staleness + sync integration
# =============================================================================


@pytest.mark.asyncio
async def test_empty_projection_triggers_github_api_sync() -> None:
    """When projection is empty, list_installations() is called to bootstrap."""
    raw_installations = [
        {"id": "inst-1", "account": {"id": 1, "login": "acme", "type": "Org"}, "permissions": {}}
    ]
    raw_repos = [_make_repo(1)]

    mock_client = MagicMock()
    mock_client.list_installations = AsyncMock(return_value=raw_installations)
    mock_client.list_accessible_repos = AsyncMock(return_value=raw_repos)

    mock_projection = MagicMock()
    mock_projection.get_all_active = AsyncMock(return_value=[])
    synced_inst = _make_installation_with_synced_at(datetime.now(UTC))
    synced_inst.installation_id = "inst-1"
    mock_projection.upsert_from_github_api = AsyncMock(return_value=synced_inst)

    with (
        patch("syn_api.routes.github.ensure_connected", new_callable=AsyncMock) as mock_ensure,
        patch("syn_adapters.github.client.get_github_client", return_value=mock_client),
        patch(
            "syn_domain.contexts.github.slices.get_installation.projection.get_installation_projection",
            return_value=mock_projection,
        ),
    ):
        result = await _aggregate()
        mock_ensure.assert_awaited_once()

    mock_client.list_installations.assert_awaited_once()
    assert isinstance(result, Ok)
    assert len(result.value.repos) == 1


@pytest.mark.asyncio
async def test_recently_synced_projection_still_refreshes() -> None:
    """However recent the cache, list_installations() is asked: it may predate an installation."""
    cached_inst = _make_installation_with_synced_at(datetime.now(UTC) - timedelta(minutes=1))
    cached_inst.installation_id = "inst-1"

    raw_installations = [
        {"id": "inst-1", "account": {"id": 1, "login": "acme", "type": "Org"}, "permissions": {}}
    ]

    mock_client = MagicMock()
    mock_client.list_installations = AsyncMock(return_value=raw_installations)
    mock_client.list_accessible_repos = AsyncMock(return_value=[_make_repo(1)])

    mock_projection = MagicMock()
    mock_projection.get_all_active = AsyncMock(return_value=[cached_inst])
    mock_projection.upsert_from_github_api = AsyncMock(return_value=cached_inst)

    with (
        patch("syn_api.routes.github.ensure_connected", new_callable=AsyncMock) as mock_ensure,
        patch("syn_adapters.github.client.get_github_client", return_value=mock_client),
        patch(
            "syn_domain.contexts.github.slices.get_installation.projection.get_installation_projection",
            return_value=mock_projection,
        ),
    ):
        await _aggregate()

    mock_ensure.assert_awaited_once()
    mock_client.list_installations.assert_awaited_once()


@pytest.mark.asyncio
async def test_sync_failure_returns_empty_gracefully() -> None:
    """If list_installations() raises, the endpoint returns empty, marked unavailable."""
    mock_client = MagicMock()
    mock_client.list_installations = AsyncMock(side_effect=RuntimeError("network error"))

    mock_projection = MagicMock()
    mock_projection.get_all_active = AsyncMock(return_value=[])

    with (
        patch("syn_api.routes.github.ensure_connected", new_callable=AsyncMock) as mock_ensure,
        patch("syn_adapters.github.client.get_github_client", return_value=mock_client),
        patch(
            "syn_domain.contexts.github.slices.get_installation.projection.get_installation_projection",
            return_value=mock_projection,
        ),
    ):
        result = await _aggregate()
        mock_ensure.assert_awaited_once()

    # Ok([]) alone is vacuous here: an empty projection produces [] whether or
    # not the sync ran at all. Assert the failing call actually happened, so the
    # test proves the FAILURE path was exercised rather than skipped.
    mock_client.list_installations.assert_awaited_once_with()
    assert isinstance(result, Ok)
    assert result.value.repos == []
    # Empty because GitHub failed, not because the App reaches nothing.
    assert result.value.lookup == GitHubRepoLookup.UNAVAILABLE


async def test_no_github_app_is_a_clean_not_configured_error() -> None:
    """A fresh install with no GitHub App returned 500 from GET /github/repos
    (release rehearsal 2026-10-10). The factory's refusal must map to a
    NOT_CONFIGURED result, which the endpoint turns into a 503."""
    from fastapi import HTTPException

    from syn_adapters.github.client import GitHubNotConfiguredError
    from syn_api.routes.github import list_accessible_repos_endpoint

    with (
        patch.object(github_routes, "ensure_connected", AsyncMock()),
        patch(
            "syn_adapters.github.client.get_github_client",
            side_effect=GitHubNotConfiguredError(
                "GitHub App not configured. Set SYN_GITHUB_APP_ID"
            ),
        ),
    ):
        result = await list_accessible_repos(installation_id="12345")
        assert isinstance(result, Err)
        assert result.error == GitHubError.NOT_CONFIGURED
        assert "not configured" in result.message

        with pytest.raises(HTTPException) as exc:
            await list_accessible_repos_endpoint(installation_id="12345")
        assert exc.value.status_code == 503
        assert "not configured" in str(exc.value.detail)
