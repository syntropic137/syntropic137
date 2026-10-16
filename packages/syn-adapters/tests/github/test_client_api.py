"""A 429 is a rate limit, and says when to try again (platform-dispatched evidence, A.8).

Before, only a 403 whose body mentioned "rate limit" was one. A 429 - what
GitHub answers for a secondary limit - surfaced as a generic
`GitHubAppError(status_code=429)`, so a caller could not tell "wait and try
again" from "GitHub refused", and the wait GitHub asked for in `Retry-After`
was thrown away.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from typing import TYPE_CHECKING, cast

import httpx
import pytest

from syn_adapters.github.client import GitHubAppError, GitHubRateLimitError
from syn_adapters.github.client_api import api_get, check_response

if TYPE_CHECKING:
    from syn_adapters.github.client import GitHubAppClient

pytestmark = pytest.mark.unit

# Slack for the clock moving between building a response and reading it.
_TOLERANCE = timedelta(seconds=5)


def _response(status: int, headers: dict[str, str] | None = None, text: str = "") -> httpx.Response:
    return httpx.Response(
        status,
        headers=headers,
        text=text,
        request=httpx.Request("GET", "https://api.github.com/repos/o/r/actions/runs"),
    )


def _rate_limited(response: httpx.Response) -> GitHubRateLimitError:
    with pytest.raises(GitHubRateLimitError) as raised:
        check_response(response)
    return raised.value


class TestA429IsARateLimit:
    def test_retry_after_in_seconds_sets_the_reset(self) -> None:
        before = datetime.now(UTC)

        error = _rate_limited(_response(429, {"Retry-After": "120"}))

        assert error.reset_at is not None
        assert before + timedelta(seconds=120) <= error.reset_at
        assert error.reset_at <= before + timedelta(seconds=120) + _TOLERANCE

    def test_retry_after_as_an_http_date_sets_the_reset(self) -> None:
        when = (datetime.now(UTC) + timedelta(minutes=10)).replace(microsecond=0)

        error = _rate_limited(_response(429, {"Retry-After": format_datetime(when, usegmt=True)}))

        assert error.reset_at is not None
        assert abs(error.reset_at - when) <= _TOLERANCE

    def test_retry_after_wins_over_the_primary_limit_reset(self) -> None:
        """A secondary limit's wait is `Retry-After`; `X-RateLimit-Reset` is the hourly window."""
        hourly = datetime.now(UTC) + timedelta(hours=1)
        before = datetime.now(UTC)

        error = _rate_limited(
            _response(429, {"Retry-After": "30", "X-RateLimit-Reset": str(int(hourly.timestamp()))})
        )

        assert error.reset_at is not None
        assert error.reset_at <= before + timedelta(seconds=30) + _TOLERANCE

    def test_without_retry_after_the_primary_limit_reset_is_used(self) -> None:
        reset = datetime(2030, 1, 1, tzinfo=UTC)

        error = _rate_limited(_response(429, {"X-RateLimit-Reset": str(int(reset.timestamp()))}))

        assert error.reset_at == reset

    def test_without_any_header_it_is_still_a_rate_limit(self) -> None:
        """GitHub said nothing about when; the caller still learns it was throttled."""
        error = _rate_limited(_response(429))

        assert error.reset_at is None


class TestA403RateLimitAlsoReadsRetryAfter:
    def test_a_secondary_limit_403_carries_its_retry_after(self) -> None:
        before = datetime.now(UTC)

        error = _rate_limited(
            _response(403, {"Retry-After": "60"}, text="You have exceeded a secondary rate limit.")
        )

        assert error.reset_at is not None
        assert before + timedelta(seconds=60) <= error.reset_at

    def test_a_plain_403_is_not_a_rate_limit(self) -> None:
        with pytest.raises(GitHubAppError) as raised:
            check_response(_response(403, text="Resource not accessible by integration"))

        assert not isinstance(raised.value, GitHubRateLimitError)
        assert raised.value.status_code == 403


class _FakeHttp:
    def __init__(self, response: httpx.Response) -> None:
        self._response = response

    async def get(self, path: str, headers: dict[str, str] | None = None) -> httpx.Response:
        del path, headers
        return self._response


class _FakeClient:
    """The surface `api_get` uses of GitHubAppClient."""

    def __init__(self, response: httpx.Response) -> None:
        self._http = _FakeHttp(response)

    async def get_installation_token(self, installation_id: str | None) -> str:
        del installation_id
        return "ghs_test"


async def test_a_caller_of_the_api_sees_the_rate_limit_not_a_generic_error() -> None:
    """The hop that consumes `check_response`: an installation GET answered 429."""
    client = cast("GitHubAppClient", _FakeClient(_response(429, {"Retry-After": "5"})))

    with pytest.raises(GitHubRateLimitError) as raised:
        await api_get(client, "/repos/o/r/actions/runs", installation_id="42")

    assert raised.value.reset_at is not None
