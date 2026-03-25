"""Unit tests for webhook service functions (list_repos, get_installation)."""

from __future__ import annotations

from dataclasses import dataclass, field
from unittest.mock import AsyncMock, patch

import pytest

from syn_api.routes.webhooks.services import (
    _collect_all_repos,
    _get_repos_for_installation,
    _normalize_repos,
    get_installation,
    list_repos,
)
from syn_api.types import Err, Ok


@dataclass
class FakeInstallation:
    installation_id: str = "123"
    account_name: str = "test-org"
    status: str = "active"
    repositories: list[str] = field(default_factory=lambda: ["org/repo-a", "org/repo-b"])
    installed_at: str = "2026-01-01"


# --- _normalize_repos ---


def test_normalize_repos_strings_become_dicts() -> None:
    result = _normalize_repos(["org/repo-a", "org/repo-b"])
    assert result == [{"full_name": "org/repo-a"}, {"full_name": "org/repo-b"}]


def test_normalize_repos_dicts_pass_through() -> None:
    repos = [{"full_name": "org/repo-a", "private": True}]
    assert _normalize_repos(repos) == repos


def test_normalize_repos_empty_list() -> None:
    assert _normalize_repos([]) == []


# --- _get_repos_for_installation ---


@pytest.mark.anyio
async def test_get_repos_for_installation_found() -> None:
    projection = AsyncMock()
    projection.get.return_value = FakeInstallation()
    result = await _get_repos_for_installation(projection, "123")
    assert isinstance(result, Ok)
    assert len(result.value) == 2


@pytest.mark.anyio
async def test_get_repos_for_installation_not_found() -> None:
    projection = AsyncMock()
    projection.get.return_value = None
    result = await _get_repos_for_installation(projection, "999")
    assert isinstance(result, Err)
    assert "not found" in (result.message or "").lower()


# --- _collect_all_repos ---


@pytest.mark.anyio
async def test_collect_all_repos() -> None:
    projection = AsyncMock()
    projection.get_all_active.return_value = [
        FakeInstallation(repositories=["org/a"]),
        FakeInstallation(repositories=["org/b", "org/c"]),
    ]
    result = await _collect_all_repos(projection)
    assert result == ["org/a", "org/b", "org/c"]


# --- list_repos ---


@pytest.mark.anyio
async def test_list_repos_single_installation() -> None:
    with (
        patch("syn_api.routes.webhooks.services.ensure_connected", new_callable=AsyncMock),
        patch(
            "syn_api.routes.webhooks.services.get_installation_projection",
            create=True,
        ) as mock_proj_fn,
    ):
        # Patch the lazy import
        mock_proj = AsyncMock()
        mock_proj.get.return_value = FakeInstallation()
        mock_proj_fn.return_value = mock_proj

        with patch(
            "syn_domain.contexts.github.slices.get_installation.projection.get_installation_projection",
            mock_proj_fn,
        ):
            result = await list_repos(installation_id="123")

    assert isinstance(result, Ok)
    assert len(result.value) == 2
    assert result.value[0] == {"full_name": "org/repo-a"}


@pytest.mark.anyio
async def test_list_repos_pagination() -> None:
    with (
        patch("syn_api.routes.webhooks.services.ensure_connected", new_callable=AsyncMock),
        patch(
            "syn_domain.contexts.github.slices.get_installation.projection.get_installation_projection",
        ) as mock_proj_fn,
    ):
        mock_proj = AsyncMock()
        mock_proj.get.return_value = FakeInstallation(
            repositories=[f"org/repo-{i}" for i in range(10)]
        )
        mock_proj_fn.return_value = mock_proj

        result = await list_repos(installation_id="123", limit=3, offset=2)

    assert isinstance(result, Ok)
    assert len(result.value) == 3
    assert result.value[0] == {"full_name": "org/repo-2"}


# --- get_installation ---


@pytest.mark.anyio
async def test_get_installation_found() -> None:
    with (
        patch("syn_api.routes.webhooks.services.ensure_connected", new_callable=AsyncMock),
        patch(
            "syn_domain.contexts.github.slices.get_installation.projection.get_installation_projection",
        ) as mock_proj_fn,
    ):
        mock_proj = AsyncMock()
        mock_proj.get.return_value = FakeInstallation()
        mock_proj_fn.return_value = mock_proj

        result = await get_installation("123")

    assert isinstance(result, Ok)
    assert result.value["account"] == "test-org"
    assert result.value["installation_id"] == "123"


@pytest.mark.anyio
async def test_get_installation_not_found() -> None:
    with (
        patch("syn_api.routes.webhooks.services.ensure_connected", new_callable=AsyncMock),
        patch(
            "syn_domain.contexts.github.slices.get_installation.projection.get_installation_projection",
        ) as mock_proj_fn,
    ):
        mock_proj = AsyncMock()
        mock_proj.get.return_value = None
        mock_proj_fn.return_value = mock_proj

        result = await get_installation("999")

    assert isinstance(result, Err)
    assert "not found" in (result.message or "").lower()
