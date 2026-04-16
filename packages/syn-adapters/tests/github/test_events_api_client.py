"""Tests for ``GitHubEventsAPIClient`` -- the ``GitHubEventsAPIPort`` adapter.

The adapter is now stateless (the cursor lives in the domain), and rate-limit
errors are translated into ``EventsAPIResult.rate_limited=True`` rather than
raised.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from syn_adapters.github.events_api_client import GitHubEventsAPIClient


def _make_mock_client() -> MagicMock:
    """Create a mock ``GitHubAppClient`` with async HTTP and token methods."""
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
    resp.request = MagicMock()
    resp.request.headers = {"Authorization": "Bearer test-token-123"}
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
        result = await client.fetch_repo_events("owner", "repo", "inst-1")

        assert result.has_new is True
        assert result.events == events
        assert result.poll_interval_hint == 60
        assert result.rate_limited is False

    @pytest.mark.asyncio
    async def test_uses_installation_token(self) -> None:
        mock_gh = _make_mock_client()
        mock_gh._http.get.return_value = _make_response()

        client = GitHubEventsAPIClient(mock_gh)
        await client.fetch_repo_events("owner", "repo", "inst-1")

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
        result = await client.fetch_repo_events("owner", "repo", "inst-1")

        assert result.poll_interval_hint == 120


@pytest.mark.unit
class TestEventsAPIClient304:
    """Tests for 304 Not Modified responses."""

    @pytest.mark.asyncio
    async def test_returns_no_events_on_304(self) -> None:
        mock_gh = _make_mock_client()
        mock_gh._http.get.return_value = _make_response(status_code=304)

        client = GitHubEventsAPIClient(mock_gh)
        result = await client.fetch_repo_events("owner", "repo", "inst-1", etag='"prev"')

        assert result.has_new is False
        assert result.events == []
        # ETag is echoed back so the caller can persist it.
        assert result.etag == '"prev"'

    @pytest.mark.asyncio
    async def test_poll_interval_preserved_on_304(self) -> None:
        mock_gh = _make_mock_client()
        mock_gh._http.get.return_value = _make_response(
            status_code=304, headers={"X-Poll-Interval": "90", "ETag": ""}
        )

        client = GitHubEventsAPIClient(mock_gh)
        result = await client.fetch_repo_events("owner", "repo", "inst-1")

        assert result.poll_interval_hint == 90


@pytest.mark.unit
class TestEventsAPIClientETagConditional:
    """The adapter is stateless; the cursor is supplied by the caller."""

    @pytest.mark.asyncio
    async def test_returns_etag_from_response(self) -> None:
        mock_gh = _make_mock_client()
        mock_gh._http.get.return_value = _make_response(
            json_data=[{"id": "1"}], headers={"ETag": '"etag-v1"', "X-Poll-Interval": "60"}
        )

        client = GitHubEventsAPIClient(mock_gh)
        result = await client.fetch_repo_events("owner", "repo", "inst-1")

        assert result.etag == '"etag-v1"'

    @pytest.mark.asyncio
    async def test_sends_if_none_match_when_caller_supplies_etag(self) -> None:
        mock_gh = _make_mock_client()
        mock_gh._http.get.return_value = _make_response(status_code=304)

        client = GitHubEventsAPIClient(mock_gh)
        await client.fetch_repo_events("owner", "repo", "inst-1", etag='"etag-v1"')

        call = mock_gh._http.get.call_args
        headers = call.kwargs.get("headers", call[1].get("headers", {}))
        assert headers.get("If-None-Match") == '"etag-v1"'

    @pytest.mark.asyncio
    async def test_no_if_none_match_when_caller_omits_etag(self) -> None:
        mock_gh = _make_mock_client()
        mock_gh._http.get.return_value = _make_response()

        client = GitHubEventsAPIClient(mock_gh)
        await client.fetch_repo_events("owner", "repo", "inst-1")

        call = mock_gh._http.get.call_args
        headers = call.kwargs.get("headers", call[1].get("headers", {}))
        assert "If-None-Match" not in headers


@pytest.mark.unit
class TestEventsAPIClientRateLimit:
    """Rate-limit translation: port returns rate_limited=True, never raises."""

    @pytest.mark.asyncio
    async def test_rate_limit_returns_rate_limited_result(self) -> None:
        mock_gh = _make_mock_client()
        resp = _make_response(status_code=403)
        resp.text = "API rate limit exceeded"
        resp.headers["X-RateLimit-Reset"] = "1700000000"
        mock_gh._http.get.return_value = resp

        client = GitHubEventsAPIClient(mock_gh)
        result = await client.fetch_repo_events("owner", "repo", "inst-1")

        assert result.rate_limited is True
        assert result.events == []
        assert result.has_new is False
        assert result.retry_after_seconds >= 0.0
