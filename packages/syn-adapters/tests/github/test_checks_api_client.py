"""Unit tests for GitHubChecksAPIClient (#602)."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from syn_adapters.github.checks_api_client import CheckRunsResponse, GitHubChecksAPIClient


def _make_mock_github_client() -> MagicMock:
    """Create a mock GitHubAppClient with api_get."""
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
class TestGetCheckRunsForRef:
    @pytest.mark.asyncio
    async def test_returns_check_runs(self) -> None:
        mock_gh = _make_mock_github_client()
        check_runs = [_make_check_run(check_id=1), _make_check_run(check_id=2)]
        mock_gh.api_get.return_value = {"check_runs": check_runs, "total_count": 2}

        client = GitHubChecksAPIClient(mock_gh)
        result = await client.get_check_runs_for_ref("owner", "repo", "abc123", "inst-1")

        assert isinstance(result, CheckRunsResponse)
        assert len(result.check_runs) == 2
        assert result.total_count == 2
        mock_gh.api_get.assert_awaited_once_with(
            "/repos/owner/repo/commits/abc123/check-runs",
            installation_id="inst-1",
        )

    @pytest.mark.asyncio
    async def test_empty_check_runs(self) -> None:
        mock_gh = _make_mock_github_client()
        mock_gh.api_get.return_value = {"check_runs": [], "total_count": 0}

        client = GitHubChecksAPIClient(mock_gh)
        result = await client.get_check_runs_for_ref("owner", "repo", "abc123", "inst-1")

        assert result.check_runs == []
        assert result.total_count == 0

    @pytest.mark.asyncio
    async def test_total_count_defaults_to_list_length(self) -> None:
        """If total_count is missing from response, fall back to len(check_runs)."""
        mock_gh = _make_mock_github_client()
        mock_gh.api_get.return_value = {"check_runs": [_make_check_run()]}

        client = GitHubChecksAPIClient(mock_gh)
        result = await client.get_check_runs_for_ref("owner", "repo", "abc123", "inst-1")

        assert result.total_count == 1
