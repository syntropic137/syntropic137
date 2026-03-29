"""Integration tests for GitHubEventsAPIClient — ETag caching, polling, error handling."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from syn_adapters.github.events_api_client import GitHubEventsAPIClient


def _make_mock_client() -> MagicMock:
    """Create a mock GitHubAppClient with async HTTP and token methods."""
    client = MagicMock()
    client.get_installation_token = AsyncMock(return_value="test-token-123")
    client._http = MagicMock()
    client._http.get = AsyncMock()
    return client


def _make_response(
    status_code: int = 200,
    json_data: list | None = None,
    headers: dict[str, str] | None = None,
) -> MagicMock:
    """Create a mock httpx response."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.headers = {
        "X-Poll-Interval": "60",
        "ETag": '"abc123"',
        **(headers or {}),
    }
    resp.json.return_value = json_data or []
    resp.text = ""
    return resp


@pytest.mark.unit
class TestEventsAPIClient200:
    """Tests for successful 200 responses with events."""

    @pytest.mark.asyncio
    async def test_returns_events_on_200(self) -> None:
        mock_gh = _make_mock_client()
        events = [{"id": "1", "type": "PushEvent", "payload": {}}]
        mock_gh._http.get.return_value = _make_response(json_data=events)

        client = GitHubEventsAPIClient(mock_gh)
        result = await client.poll_repo_events("owner", "repo", "inst-1")

        assert result.has_new_events is True
        assert result.events == events
        assert result.poll_interval == 60

    @pytest.mark.asyncio
    async def test_uses_installation_token(self) -> None:
        mock_gh = _make_mock_client()
        mock_gh._http.get.return_value = _make_response()

        client = GitHubEventsAPIClient(mock_gh)
        await client.poll_repo_events("owner", "repo", "inst-1")

        mock_gh.get_installation_token.assert_awaited_once_with("inst-1")
        actual_headers = mock_gh._http.get.call_args.kwargs.get("headers", {})
        assert actual_headers.get("Authorization") == "Bearer test-token-123"

    @pytest.mark.asyncio
    async def test_respects_x_poll_interval_header(self) -> None:
        mock_gh = _make_mock_client()
        mock_gh._http.get.return_value = _make_response(
            headers={"X-Poll-Interval": "120", "ETag": '"e1"'}
        )

        client = GitHubEventsAPIClient(mock_gh)
        result = await client.poll_repo_events("owner", "repo", "inst-1")

        assert result.poll_interval == 120


@pytest.mark.unit
class TestEventsAPIClient304:
    """Tests for 304 Not Modified responses."""

    @pytest.mark.asyncio
    async def test_returns_no_events_on_304(self) -> None:
        mock_gh = _make_mock_client()
        # First call: 200 with ETag
        mock_gh._http.get.return_value = _make_response(
            json_data=[{"id": "1", "type": "PushEvent", "payload": {}}]
        )
        client = GitHubEventsAPIClient(mock_gh)
        await client.poll_repo_events("owner", "repo", "inst-1")

        # Second call: 304 Not Modified
        mock_gh._http.get.return_value = _make_response(status_code=304)
        result = await client.poll_repo_events("owner", "repo", "inst-1")

        assert result.has_new_events is False
        assert result.events == []

    @pytest.mark.asyncio
    async def test_poll_interval_preserved_on_304(self) -> None:
        mock_gh = _make_mock_client()
        mock_gh._http.get.return_value = _make_response(
            status_code=304, headers={"X-Poll-Interval": "90", "ETag": ""}
        )

        client = GitHubEventsAPIClient(mock_gh)
        result = await client.poll_repo_events("owner", "repo", "inst-1")

        assert result.poll_interval == 90


@pytest.mark.unit
class TestEventsAPIClientETagCaching:
    """Tests for ETag conditional request handling."""

    @pytest.mark.asyncio
    async def test_stores_etag_from_200_response(self) -> None:
        mock_gh = _make_mock_client()
        mock_gh._http.get.return_value = _make_response(
            json_data=[{"id": "1"}], headers={"ETag": '"etag-v1"', "X-Poll-Interval": "60"}
        )

        client = GitHubEventsAPIClient(mock_gh)
        await client.poll_repo_events("owner", "repo", "inst-1")

        assert client._etags["owner/repo"] == '"etag-v1"'

    @pytest.mark.asyncio
    async def test_sends_if_none_match_on_subsequent_request(self) -> None:
        mock_gh = _make_mock_client()
        mock_gh._http.get.return_value = _make_response(
            json_data=[{"id": "1"}], headers={"ETag": '"etag-v1"', "X-Poll-Interval": "60"}
        )

        client = GitHubEventsAPIClient(mock_gh)
        # First call stores the ETag
        await client.poll_repo_events("owner", "repo", "inst-1")

        # Second call should include If-None-Match
        mock_gh._http.get.return_value = _make_response(status_code=304)
        await client.poll_repo_events("owner", "repo", "inst-1")

        second_call_kwargs = mock_gh._http.get.call_args
        headers = second_call_kwargs.kwargs.get("headers", second_call_kwargs[1].get("headers", {}))
        assert headers.get("If-None-Match") == '"etag-v1"'

    @pytest.mark.asyncio
    async def test_no_if_none_match_on_first_request(self) -> None:
        mock_gh = _make_mock_client()
        mock_gh._http.get.return_value = _make_response()

        client = GitHubEventsAPIClient(mock_gh)
        await client.poll_repo_events("owner", "repo", "inst-1")

        first_call_kwargs = mock_gh._http.get.call_args
        headers = first_call_kwargs.kwargs.get("headers", first_call_kwargs[1].get("headers", {}))
        assert "If-None-Match" not in headers

    @pytest.mark.asyncio
    async def test_etags_scoped_per_repo(self) -> None:
        mock_gh = _make_mock_client()
        mock_gh._http.get.return_value = _make_response(
            json_data=[{"id": "1"}], headers={"ETag": '"etag-repo-a"', "X-Poll-Interval": "60"}
        )

        client = GitHubEventsAPIClient(mock_gh)
        await client.poll_repo_events("owner", "repo-a", "inst-1")

        mock_gh._http.get.return_value = _make_response(
            json_data=[{"id": "2"}], headers={"ETag": '"etag-repo-b"', "X-Poll-Interval": "60"}
        )
        await client.poll_repo_events("owner", "repo-b", "inst-1")

        assert client._etags["owner/repo-a"] == '"etag-repo-a"'
        assert client._etags["owner/repo-b"] == '"etag-repo-b"'


@pytest.mark.unit
class TestEventsAPIClientErrors:
    """Tests for error responses (rate limits, auth errors)."""

    @pytest.mark.asyncio
    async def test_rate_limit_raises_error(self) -> None:
        from syn_adapters.github.client import GitHubRateLimitError

        mock_gh = _make_mock_client()
        resp = _make_response(status_code=403)
        resp.text = "API rate limit exceeded"
        resp.headers["X-RateLimit-Reset"] = "1700000000"
        mock_gh._http.get.return_value = resp

        client = GitHubEventsAPIClient(mock_gh)
        with pytest.raises(GitHubRateLimitError):
            await client.poll_repo_events("owner", "repo", "inst-1")

    @pytest.mark.asyncio
    async def test_404_raises_app_error(self) -> None:
        from syn_adapters.github.client import GitHubAppError

        mock_gh = _make_mock_client()
        resp = _make_response(status_code=404)
        resp.text = "Not Found"
        mock_gh._http.get.return_value = resp

        client = GitHubEventsAPIClient(mock_gh)
        with pytest.raises(GitHubAppError):
            await client.poll_repo_events("owner", "repo", "inst-1")
