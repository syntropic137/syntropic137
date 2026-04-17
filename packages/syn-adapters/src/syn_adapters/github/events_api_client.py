"""GitHub Events API adapter -- implements ``GitHubEventsAPIPort``.

Stateless HTTP adapter. All cursor/HWM state is owned by the domain
service (``GitHubRepoIngestionService``); this adapter only translates
HTTP into the typed ``EventsAPIResult``. Rate-limit errors are caught
internally and surfaced as ``rate_limited=True`` -- the port is total,
no exception types leak across the hexagonal boundary.

See ADR-060 Section 9 (8-layer defense) and Section 10 (hexagonal layout).
"""

from __future__ import annotations

import logging
import re as _re
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from syn_domain.contexts.github.ports.events_api_port import (
    EventsAPIResult,
    GitHubEventsAPIPort,
)

if TYPE_CHECKING:
    import httpx

    from syn_adapters.github.client import GitHubAppClient

logger = logging.getLogger(__name__)

GitHubEventPayload = dict[str, Any]

_MAX_PAGES = 10
_DEFAULT_RATE_LIMIT_BACKOFF_SECONDS = 60.0


def _parse_next_link(link_header: str) -> str | None:
    """Extract the ``rel="next"`` URL from a GitHub Link header."""
    if not link_header:
        return None
    for part in link_header.split(","):
        if 'rel="next"' in part:
            match = _re.search(r"<([^>]+)>", part)
            if match:
                return match.group(1)
    return None


def _empty_result(etag: str | None, poll_interval: int) -> EventsAPIResult:
    """Empty result preserving the caller's etag so the next request stays conditional."""
    return EventsAPIResult(
        events=[],
        has_new=False,
        etag=etag or "",
        poll_interval_hint=poll_interval,
    )


def _rate_limited_result(etag: str | None, reset_at: datetime | None) -> EventsAPIResult:
    """Translate a rate-limit error into an empty ``EventsAPIResult``.

    ``poll_interval_hint`` is the port's X-Poll-Interval minimum (seconds
    between polls in steady state) and is kept at the constant default so
    callers never treat a multi-minute rate-limit reset as the recommended
    cadence. The actual backoff is carried on ``retry_after_seconds``.
    """
    wait = _DEFAULT_RATE_LIMIT_BACKOFF_SECONDS
    if reset_at is not None:
        wait = max((reset_at - datetime.now(UTC)).total_seconds(), 0.0)
    return EventsAPIResult(
        events=[],
        has_new=False,
        etag=etag or "",
        poll_interval_hint=int(_DEFAULT_RATE_LIMIT_BACKOFF_SECONDS),
        rate_limited=True,
        retry_after_seconds=wait,
    )


class GitHubEventsAPIClient(GitHubEventsAPIPort):
    """Stateless adapter implementing ``GitHubEventsAPIPort``.

    Subclasses the Protocol explicitly so the ``test_port_adoption`` fitness
    check can verify implementation at CI time. Bypassing the port would
    require breaking that subclass relationship.
    """

    def __init__(self, github_client: GitHubAppClient) -> None:
        self._client = github_client

    async def fetch_repo_events(
        self,
        owner: str,
        repo: str,
        installation_id: str,
        etag: str | None = None,
    ) -> EventsAPIResult:
        from syn_adapters.github.client import GitHubRateLimitError

        path = f"/repos/{owner}/{repo}/events"

        try:
            response = await self._send_events_request(path, installation_id, etag)
        except GitHubRateLimitError as exc:
            return _rate_limited_result(etag, exc.reset_at)

        return await self._translate_response(response, etag)

    async def _send_events_request(
        self,
        path: str,
        installation_id: str,
        etag: str | None,
    ) -> httpx.Response:
        """Build headers, get a token, and issue the conditional GET."""
        token = await self._client.get_installation_token(installation_id)
        headers: dict[str, str] = {"Authorization": f"Bearer {token}"}
        if etag:
            headers["If-None-Match"] = etag
        return await self._client._http.get(path, headers=headers)

    async def _translate_response(
        self,
        response: httpx.Response,
        etag: str | None,
    ) -> EventsAPIResult:
        """Map an HTTP response to an ``EventsAPIResult``, honoring rate limits.

        The port is total: ``GitHubRateLimitError`` surfaces as
        ``rate_limited=True`` and any other ``GitHubAppError`` (auth, 404,
        5xx) is logged and translated into an empty result so no adapter
        exception type leaks across the hexagonal boundary.
        """
        from syn_adapters.github.client import GitHubAppError, GitHubRateLimitError
        from syn_adapters.github.client_api import check_response

        poll_interval = int(response.headers.get("X-Poll-Interval", "60"))

        if response.status_code == 304:
            return _empty_result(etag, poll_interval)
        if response.status_code == 200:
            return await self._handle_success(response, poll_interval)

        try:
            check_response(response)
        except GitHubRateLimitError as exc:
            return _rate_limited_result(etag, exc.reset_at)
        except GitHubAppError as exc:
            logger.warning(
                "Events API returned %s (non-rate-limit); returning empty result: %s",
                response.status_code,
                exc,
            )
            return _empty_result(etag, poll_interval)

        return _empty_result(etag, poll_interval)

    async def _handle_success(
        self,
        response: httpx.Response,
        poll_interval: int,
    ) -> EventsAPIResult:
        response_etag = response.headers.get("ETag", "")

        data = response.json()
        events: list[GitHubEventPayload] = data if isinstance(data, list) else []

        auth_header = response.request.headers.get("Authorization", "")
        link_header = response.headers.get("Link", "")
        extra = await self._fetch_remaining_pages(link_header, auth_header)
        events.extend(extra)

        return EventsAPIResult(
            events=events,
            has_new=bool(events),
            etag=response_etag,
            poll_interval_hint=poll_interval,
        )

    async def _fetch_remaining_pages(
        self,
        link_header: str,
        auth_header: str,
    ) -> list[GitHubEventPayload]:
        extra_events: list[GitHubEventPayload] = []
        next_url = _parse_next_link(link_header)
        pages_fetched = 1
        while next_url and pages_fetched < _MAX_PAGES:
            page_events, next_url = await self._fetch_single_page(
                next_url, auth_header, pages_fetched + 1
            )
            if page_events is None:
                break
            extra_events.extend(page_events)
            pages_fetched += 1
        return extra_events

    async def _fetch_single_page(
        self,
        url: str,
        auth_header: str,
        page_number: int,
    ) -> tuple[list[GitHubEventPayload] | None, str | None]:
        try:
            resp = await self._client._http.get(url, headers={"Authorization": auth_header})
            if resp.status_code != 200:
                logger.warning(
                    "Events API pagination stopped: page %d returned %d",
                    page_number,
                    resp.status_code,
                )
                return None, None
            page_data = resp.json()
            if not isinstance(page_data, list) or not page_data:
                return None, None
            return page_data, _parse_next_link(resp.headers.get("Link", ""))
        except Exception:
            logger.warning(
                "Failed to fetch events page %d",
                page_number,
                exc_info=True,
            )
            return None, None
