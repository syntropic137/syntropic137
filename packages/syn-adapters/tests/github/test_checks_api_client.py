"""Tests for ``GitHubChecksAPIClient`` -- the ``GitHubChecksAPIPort`` adapter."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from syn_adapters.github.checks_api_client import GitHubChecksAPIClient
from syn_domain.contexts.github.ports import ChecksAPIResult


def _make_mock_github_client() -> MagicMock:
    client = MagicMock()
    client.api_get = AsyncMock()
    return client


def _make_check_run(
    check_id: int = 1,
    name: str = "build",
    status: str = "completed",
    conclusion: str | None = "failure",
) -> dict[str, Any]:
    return {
        "id": check_id,
        "name": name,
        "status": status,
        "conclusion": conclusion,
        "html_url": f"https://github.com/owner/repo/runs/{check_id}",
        "output": {"title": f"{name} failed", "summary": "1 error"},
    }


@pytest.mark.unit
class TestFetchCheckRuns:
    @pytest.mark.asyncio
    async def test_returns_check_runs(self) -> None:
        mock_gh = _make_mock_github_client()
        check_runs = [_make_check_run(check_id=1), _make_check_run(check_id=2)]
        mock_gh.api_get.return_value = {"check_runs": check_runs, "total_count": 2}

        client = GitHubChecksAPIClient(mock_gh)
        result = await client.fetch_check_runs("owner", "repo", "abc123", "inst-1")

        assert isinstance(result, ChecksAPIResult)
        assert len(result.check_runs) == 2
        assert result.total_count == 2
        assert result.rate_limited is False
        mock_gh.api_get.assert_awaited_once_with(
            "/repos/owner/repo/commits/abc123/check-runs",
            installation_id="inst-1",
        )

    @pytest.mark.asyncio
    async def test_empty_check_runs(self) -> None:
        mock_gh = _make_mock_github_client()
        mock_gh.api_get.return_value = {"check_runs": [], "total_count": 0}

        client = GitHubChecksAPIClient(mock_gh)
        result = await client.fetch_check_runs("owner", "repo", "abc123", "inst-1")

        assert result.check_runs == []
        assert result.total_count == 0

    @pytest.mark.asyncio
    async def test_total_count_defaults_to_list_length(self) -> None:
        """If total_count is missing from response, fall back to len(check_runs)."""
        mock_gh = _make_mock_github_client()
        mock_gh.api_get.return_value = {"check_runs": [_make_check_run()]}

        client = GitHubChecksAPIClient(mock_gh)
        result = await client.fetch_check_runs("owner", "repo", "abc123", "inst-1")

        assert result.total_count == 1

    @pytest.mark.asyncio
    async def test_rate_limit_returns_rate_limited_result(self) -> None:
        from syn_adapters.github.client import GitHubRateLimitError

        mock_gh = _make_mock_github_client()
        mock_gh.api_get.side_effect = GitHubRateLimitError("rate limited")

        client = GitHubChecksAPIClient(mock_gh)
        result = await client.fetch_check_runs("owner", "repo", "abc123", "inst-1")

        assert result.rate_limited is True
        assert result.check_runs == []
        assert result.retry_after_seconds >= 0.0

    @pytest.mark.asyncio
    async def test_fetch_returns_empty_on_github_app_error(self) -> None:
        """Non-rate-limit adapter errors must not leak across the port.

        ``GitHubAppError`` (401/404/5xx) is logged and translated into an
        empty ``ChecksAPIResult`` so the domain never imports adapter
        exception types.
        """
        from syn_adapters.github.client import GitHubAppError

        mock_gh = _make_mock_github_client()
        mock_gh.api_get.side_effect = GitHubAppError("404 Not Found")

        client = GitHubChecksAPIClient(mock_gh)
        result = await client.fetch_check_runs("owner", "repo", "abc123", "inst-1")

        assert result.rate_limited is False
        assert result.check_runs == []
        assert result.total_count == 0
