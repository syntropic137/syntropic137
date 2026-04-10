"""Tests for GET /github/repos endpoint and service function."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from syn_api.routes.github import _is_stale, list_accessible_repos
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
    mock_client.list_accessible_repos = AsyncMock(side_effect=[inst1_repos, inst2_repos])

    mock_projection = MagicMock()
    mock_projection.get_all_active = AsyncMock(
        return_value=[
            _make_installation("inst-1"),
            _make_installation("inst-2"),
        ]
    )

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
    mock_client.list_accessible_repos = AsyncMock(side_effect=GitHubAuthError("bad token"))

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
    mock_client.list_accessible_repos = AsyncMock(side_effect=GitHubRateLimitError("rate limited"))

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
        result = await list_accessible_repos(installation_id="inst-1", include_private=False)

    assert isinstance(result, Ok)
    assert len(result.value) == 2
    assert all(not r.private for r in result.value)


# =============================================================================
# _is_stale helper
# =============================================================================


def _make_installation_with_synced_at(synced_at: datetime | None) -> MagicMock:
    inst = MagicMock()
    inst.synced_at = synced_at
    return inst


def test_is_stale_empty_list() -> None:
    """Empty installation list is stale."""
    assert _is_stale([]) is True


def test_is_stale_none_synced_at() -> None:
    """synced_at=None (pre-migration record) is treated as stale."""
    inst = _make_installation_with_synced_at(None)
    assert _is_stale([inst]) is True


def test_is_stale_fresh() -> None:
    """Record synced 30 minutes ago is not stale."""
    inst = _make_installation_with_synced_at(datetime.now(UTC) - timedelta(minutes=30))
    assert _is_stale([inst]) is False


def test_is_stale_past_ttl() -> None:
    """Record synced 90 minutes ago is stale."""
    inst = _make_installation_with_synced_at(datetime.now(UTC) - timedelta(minutes=90))
    assert _is_stale([inst]) is True


def test_is_stale_one_stale_record_triggers_refresh() -> None:
    """Any stale record in the list marks the whole set as stale."""
    fresh = _make_installation_with_synced_at(datetime.now(UTC) - timedelta(minutes=10))
    stale = _make_installation_with_synced_at(datetime.now(UTC) - timedelta(minutes=90))
    assert _is_stale([fresh, stale]) is True


# =============================================================================
# _aggregate_all_installations — staleness + sync integration
# =============================================================================


@pytest.mark.asyncio
async def test_empty_projection_triggers_github_api_sync() -> None:
    """When projection is empty, list_installations() is called to bootstrap."""
    raw_installations = [{"id": "inst-1", "account": {"id": 1, "login": "acme", "type": "Org"}, "permissions": {}}]
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
        patch("syn_api._wiring.ensure_connected", new_callable=AsyncMock),
        patch("syn_adapters.github.client.get_github_client", return_value=mock_client),
        patch(
            "syn_domain.contexts.github.slices.get_installation.projection.get_installation_projection",
            return_value=mock_projection,
        ),
    ):
        result = await list_accessible_repos(installation_id=None)

    mock_client.list_installations.assert_awaited_once()
    assert isinstance(result, Ok)
    assert len(result.value) == 1


@pytest.mark.asyncio
async def test_stale_projection_triggers_refresh() -> None:
    """When synced_at is past the TTL, list_installations() is called."""
    stale_inst = _make_installation_with_synced_at(datetime.now(UTC) - timedelta(minutes=90))
    stale_inst.installation_id = "inst-1"

    raw_installations = [{"id": "inst-1", "account": {"id": 1, "login": "acme", "type": "Org"}, "permissions": {}}]
    fresh_inst = _make_installation_with_synced_at(datetime.now(UTC))
    fresh_inst.installation_id = "inst-1"

    mock_client = MagicMock()
    mock_client.list_installations = AsyncMock(return_value=raw_installations)
    mock_client.list_accessible_repos = AsyncMock(return_value=[_make_repo(1)])

    mock_projection = MagicMock()
    mock_projection.get_all_active = AsyncMock(return_value=[stale_inst])
    mock_projection.upsert_from_github_api = AsyncMock(return_value=fresh_inst)

    with (
        patch("syn_api._wiring.ensure_connected", new_callable=AsyncMock),
        patch("syn_adapters.github.client.get_github_client", return_value=mock_client),
        patch(
            "syn_domain.contexts.github.slices.get_installation.projection.get_installation_projection",
            return_value=mock_projection,
        ),
    ):
        await list_accessible_repos(installation_id=None)

    mock_client.list_installations.assert_awaited_once()


@pytest.mark.asyncio
async def test_fresh_projection_skips_refresh() -> None:
    """When all records are within the TTL, list_installations() is NOT called."""
    fresh_inst = _make_installation_with_synced_at(datetime.now(UTC) - timedelta(minutes=10))
    fresh_inst.installation_id = "inst-1"

    mock_client = MagicMock()
    mock_client.list_installations = AsyncMock(return_value=[])
    mock_client.list_accessible_repos = AsyncMock(return_value=[_make_repo(1)])

    mock_projection = MagicMock()
    mock_projection.get_all_active = AsyncMock(return_value=[fresh_inst])

    with (
        patch("syn_api._wiring.ensure_connected", new_callable=AsyncMock),
        patch("syn_adapters.github.client.get_github_client", return_value=mock_client),
        patch(
            "syn_domain.contexts.github.slices.get_installation.projection.get_installation_projection",
            return_value=mock_projection,
        ),
    ):
        await list_accessible_repos(installation_id=None)

    mock_client.list_installations.assert_not_awaited()


@pytest.mark.asyncio
async def test_sync_failure_returns_empty_gracefully() -> None:
    """If list_installations() raises, the endpoint returns empty without crashing."""
    mock_client = MagicMock()
    mock_client.list_installations = AsyncMock(side_effect=RuntimeError("network error"))

    mock_projection = MagicMock()
    mock_projection.get_all_active = AsyncMock(return_value=[])

    with (
        patch("syn_api._wiring.ensure_connected", new_callable=AsyncMock),
        patch("syn_adapters.github.client.get_github_client", return_value=mock_client),
        patch(
            "syn_domain.contexts.github.slices.get_installation.projection.get_installation_projection",
            return_value=mock_projection,
        ),
    ):
        result = await list_accessible_repos(installation_id=None)

    assert isinstance(result, Ok)
    assert result.value == []
