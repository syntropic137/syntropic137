"""Tests for GET /github/repos endpoint and service function."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from syn_api.routes.github import list_accessible_repos
from syn_api.types import Err, GitHubError, Ok


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
    """Create a mock Installation read model."""
    inst = MagicMock()
    inst.installation_id = installation_id
    return inst


@pytest.mark.asyncio
async def test_single_installation() -> None:
    """Service returns repos for a specific installation."""
    raw_repos = [_make_repo(1), _make_repo(2, private=True)]

    mock_client = MagicMock()
    mock_client.list_accessible_repos = AsyncMock(return_value=raw_repos)

    with (
        patch("syn_api._wiring.ensure_connected", new_callable=AsyncMock),
        patch(
            "syn_adapters.github.client.get_github_client",
            return_value=mock_client,
        ),
    ):
        result = await list_accessible_repos(installation_id="inst-1")

    assert isinstance(result, Ok)
    assert len(result.value) == 2
    assert result.value[0].github_id == 1
    assert result.value[0].full_name == "org/repo-1"
    assert result.value[0].owner == "org"
    assert result.value[0].installation_id == "inst-1"


@pytest.mark.asyncio
async def test_all_installations_aggregated() -> None:
    """Without installation_id, aggregates from all active installations."""
    inst1_repos = [_make_repo(1), _make_repo(2)]
    inst2_repos = [_make_repo(2), _make_repo(3)]  # repo-2 is a duplicate

    mock_client = MagicMock()
    mock_client.list_accessible_repos = AsyncMock(
        side_effect=[inst1_repos, inst2_repos]
    )

    mock_projection = MagicMock()
    mock_projection.get_all_active = AsyncMock(return_value=[
        _make_installation("inst-1"),
        _make_installation("inst-2"),
    ])

    with (
        patch("syn_api._wiring.ensure_connected", new_callable=AsyncMock),
        patch(
            "syn_adapters.github.client.get_github_client",
            return_value=mock_client,
        ),
        patch(
            "syn_domain.contexts.github.slices.get_installation.projection.get_installation_projection",
            return_value=mock_projection,
        ),
    ):
        result = await list_accessible_repos(installation_id=None)

    assert isinstance(result, Ok)
    # Repo 2 appears in both installations — should be deduplicated
    assert len(result.value) == 3
    github_ids = {r.github_id for r in result.value}
    assert github_ids == {1, 2, 3}


@pytest.mark.asyncio
async def test_auth_error_maps_to_err() -> None:
    """GitHubAuthError maps to Err(AUTH_REQUIRED)."""
    from syn_adapters.github.client import GitHubAuthError

    mock_client = MagicMock()
    mock_client.list_accessible_repos = AsyncMock(
        side_effect=GitHubAuthError("bad token")
    )

    with (
        patch("syn_api._wiring.ensure_connected", new_callable=AsyncMock),
        patch(
            "syn_adapters.github.client.get_github_client",
            return_value=mock_client,
        ),
    ):
        result = await list_accessible_repos(installation_id="inst-1")

    assert isinstance(result, Err)
    assert result.error == GitHubError.AUTH_REQUIRED


@pytest.mark.asyncio
async def test_rate_limit_maps_to_err() -> None:
    """GitHubRateLimitError maps to Err(RATE_LIMITED)."""
    from syn_adapters.github.client import GitHubRateLimitError

    mock_client = MagicMock()
    mock_client.list_accessible_repos = AsyncMock(
        side_effect=GitHubRateLimitError("rate limited")
    )

    with (
        patch("syn_api._wiring.ensure_connected", new_callable=AsyncMock),
        patch(
            "syn_adapters.github.client.get_github_client",
            return_value=mock_client,
        ),
    ):
        result = await list_accessible_repos(installation_id="inst-1")

    assert isinstance(result, Err)
    assert result.error == GitHubError.RATE_LIMITED


@pytest.mark.asyncio
async def test_include_private_false_filters() -> None:
    """include_private=False filters out private repos."""
    raw_repos = [_make_repo(1), _make_repo(2, private=True), _make_repo(3)]

    mock_client = MagicMock()
    mock_client.list_accessible_repos = AsyncMock(return_value=raw_repos)

    with (
        patch("syn_api._wiring.ensure_connected", new_callable=AsyncMock),
        patch(
            "syn_adapters.github.client.get_github_client",
            return_value=mock_client,
        ),
    ):
        result = await list_accessible_repos(
            installation_id="inst-1", include_private=False
        )

    assert isinstance(result, Ok)
    assert len(result.value) == 2
    assert all(not r.private for r in result.value)
