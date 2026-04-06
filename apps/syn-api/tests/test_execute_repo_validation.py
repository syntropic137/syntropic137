"""Tests for GitHub App repo pre-validation in execute workflow endpoint (#598)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from syn_api.routes.executions.commands import _parse_repo_from_url, _validate_repo_access

# -- _parse_repo_from_url tests -----------------------------------------------


class TestParseRepoFromUrl:
    def test_github_https_url(self) -> None:
        assert _parse_repo_from_url("https://github.com/owner/repo") == "owner/repo"

    def test_trailing_slash(self) -> None:
        assert _parse_repo_from_url("https://github.com/owner/repo/") == "owner/repo"

    def test_none(self) -> None:
        assert _parse_repo_from_url(None) is None

    def test_empty_string(self) -> None:
        assert _parse_repo_from_url("") is None

    def test_no_slash(self) -> None:
        assert _parse_repo_from_url("skip") is None

    def test_short_path(self) -> None:
        assert _parse_repo_from_url("owner/repo") == "owner/repo"


# -- _validate_repo_access tests -----------------------------------------------


@pytest.mark.asyncio
async def test_validate_skips_when_no_repo_url() -> None:
    """No-op when repo URL is None (non-GitHub workflow)."""
    await _validate_repo_access(None)  # Should not raise


@pytest.mark.asyncio
async def test_validate_skips_when_github_app_not_configured() -> None:
    """No-op when GitHub App is not configured."""
    mock_settings = MagicMock()
    mock_settings.is_configured = False

    with patch(
        "syn_shared.settings.github.GitHubAppSettings",
        return_value=mock_settings,
    ):
        await _validate_repo_access("https://github.com/owner/repo")


@pytest.mark.asyncio
async def test_validate_raises_422_when_app_not_installed() -> None:
    """Returns 422 when GitHub App is not installed on the target repo."""
    from fastapi import HTTPException

    from syn_adapters.github.client import GitHubAuthError

    mock_settings = MagicMock()
    mock_settings.is_configured = True

    mock_client = MagicMock()
    mock_client.get_installation_for_repo = AsyncMock(
        side_effect=GitHubAuthError("GitHub App not installed on repository: owner/repo")
    )

    with (
        patch(
            "syn_shared.settings.github.GitHubAppSettings",
            return_value=mock_settings,
        ),
        patch(
            "syn_adapters.github.client.get_github_client",
            return_value=mock_client,
        ),
        pytest.raises(HTTPException) as exc_info,
    ):
        await _validate_repo_access("https://github.com/owner/repo")

    assert exc_info.value.status_code == 422
    assert "GitHub App not installed" in str(exc_info.value.detail)
    assert "owner/repo" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_validate_proceeds_on_transient_error() -> None:
    """Transient errors (network, etc.) log warning but don't block execution."""
    mock_settings = MagicMock()
    mock_settings.is_configured = True

    mock_client = MagicMock()
    mock_client.get_installation_for_repo = AsyncMock(
        side_effect=ConnectionError("network timeout")
    )

    with (
        patch(
            "syn_shared.settings.github.GitHubAppSettings",
            return_value=mock_settings,
        ),
        patch(
            "syn_adapters.github.client.get_github_client",
            return_value=mock_client,
        ),
    ):
        # Should not raise — transient errors are non-fatal
        await _validate_repo_access("https://github.com/owner/repo")


@pytest.mark.asyncio
async def test_validate_succeeds_when_app_installed() -> None:
    """No error when GitHub App is installed on the target repo."""
    mock_settings = MagicMock()
    mock_settings.is_configured = True

    mock_client = MagicMock()
    mock_client.get_installation_for_repo = AsyncMock(return_value="12345")

    with (
        patch(
            "syn_shared.settings.github.GitHubAppSettings",
            return_value=mock_settings,
        ),
        patch(
            "syn_adapters.github.client.get_github_client",
            return_value=mock_client,
        ),
    ):
        await _validate_repo_access("https://github.com/owner/repo")
