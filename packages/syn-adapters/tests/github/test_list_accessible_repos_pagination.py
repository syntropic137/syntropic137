"""Tests for list_accessible_repos pagination in client_endpoints.py."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from syn_adapters.github.client import GitHubRateLimitError
from syn_adapters.github.client_endpoints import list_accessible_repos


def _make_repo(idx: int) -> dict:
    """Create a minimal repo dict matching GitHub API shape."""
    return {
        "id": idx,
        "name": f"repo-{idx}",
        "full_name": f"org/repo-{idx}",
        "private": False,
        "default_branch": "main",
    }


def _make_response(repos: list[dict], total_count: int) -> MagicMock:
    """Create a mock httpx.Response."""
    resp = MagicMock()
    resp.status_code = 200
    resp.text = ""
    resp.json.return_value = {"total_count": total_count, "repositories": repos}
    return resp


def _make_client(responses: list[MagicMock]) -> MagicMock:
    """Create a mock GitHubAppClient with queued HTTP responses."""
    client = MagicMock()
    client.get_installation_token = AsyncMock(return_value="fake-token")
    client._http = MagicMock()
    client._http.get = AsyncMock(side_effect=responses)
    return client


@pytest.mark.asyncio
async def test_single_page() -> None:
    """Single page of results — no second request made."""
    repos = [_make_repo(i) for i in range(5)]
    client = _make_client([_make_response(repos, total_count=5)])

    result = await list_accessible_repos(client, installation_id="123")

    assert len(result) == 5
    assert result[0]["full_name"] == "org/repo-0"
    # Only one HTTP call
    assert client._http.get.call_count == 1


@pytest.mark.asyncio
async def test_multiple_pages() -> None:
    """Multi-page response — aggregates all pages."""
    page1 = [_make_repo(i) for i in range(100)]
    page2 = [_make_repo(i) for i in range(100, 200)]
    page3 = [_make_repo(i) for i in range(200, 250)]

    client = _make_client(
        [
            _make_response(page1, total_count=250),
            _make_response(page2, total_count=250),
            _make_response(page3, total_count=250),
        ]
    )

    result = await list_accessible_repos(client, installation_id="123")

    assert len(result) == 250
    assert client._http.get.call_count == 3
    # Verify pagination params on second call
    second_call = client._http.get.call_args_list[1]
    assert second_call.kwargs["params"]["page"] == 2


@pytest.mark.asyncio
async def test_empty_response() -> None:
    """Empty installation — returns empty list."""
    client = _make_client([_make_response([], total_count=0)])

    result = await list_accessible_repos(client, installation_id="123")

    assert result == []
    assert client._http.get.call_count == 1


@pytest.mark.asyncio
async def test_rate_limit_on_second_page() -> None:
    """Rate limit on page 2 — propagates GitHubRateLimitError."""
    page1 = [_make_repo(i) for i in range(100)]

    rate_limit_resp = MagicMock()
    rate_limit_resp.status_code = 403
    rate_limit_resp.text = "API rate limit exceeded"
    rate_limit_resp.headers = {"X-RateLimit-Reset": "1700000000"}

    client = _make_client(
        [
            _make_response(page1, total_count=200),
            rate_limit_resp,
        ]
    )

    with pytest.raises(GitHubRateLimitError):
        await list_accessible_repos(client, installation_id="123")


@pytest.mark.asyncio
async def test_per_page_param() -> None:
    """Verify per_page=100 is sent in the request."""
    client = _make_client([_make_response([], total_count=0)])

    await list_accessible_repos(client, installation_id="123")

    call_kwargs = client._http.get.call_args_list[0].kwargs
    assert call_kwargs["params"]["per_page"] == 100
