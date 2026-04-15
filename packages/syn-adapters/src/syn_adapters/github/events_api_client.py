"""GitHub Events API client with ETag caching for efficient polling (ISS-386).

Stateless HTTP adapter -- all cursor/ETag state management is handled by
the caller (GitHubRepoPoller via HistoricalPoller base class).

See ADR-060: Restart-safe trigger deduplication.
"""

from __future__ import annotations

import logging
import re as _re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import httpx

    from syn_adapters.github.client import GitHubAppClient

logger = logging.getLogger(__name__)

# Type alias for raw GitHub event payloads (heterogeneous JSON from Events API).
GitHubEventPayload = dict[str, Any]


@dataclass(frozen=True, slots=True)
class EventsAPIResponse:
    """Response from a single Events API poll."""

    events: list[GitHubEventPayload]
    poll_interval: int
    """``X-Poll-Interval`` header value (seconds). GitHub recommends this as
    the minimum interval between requests."""
    has_new_events: bool
    """``False`` when GitHub returned 304 Not Modified."""
    etag: str
    """ETag from the response. Caller should persist this and pass it
    back on the next poll via the ``etag`` parameter."""


def _parse_next_link(link_header: str) -> str | None:
    """Extract the 'next' URL from a GitHub Link header."""
    if not link_header:
        return None
    for part in link_header.split(","):
        if 'rel="next"' in part:
            match = _re.search(r"<([^>]+)>", part)
            if match:
                return match.group(1)
    return None


_MAX_PAGES = 10


class GitHubEventsAPIClient:
    """Stateless client for GitHub's repository Events API.

    Uses conditional requests (``If-None-Match``) when the caller
    provides a stored ETag, and respects the ``X-Poll-Interval``
    header from GitHub.

    All state management (ETag persistence, cursor tracking) is
    handled by the caller -- this client is a pure HTTP adapter.

    See: https://docs.github.com/en/rest/activity/events
    """

    def __init__(self, github_client: GitHubAppClient) -> None:
        self._client = github_client

    async def poll_repo_events(
        self,
        owner: str,
        repo: str,
        installation_id: str,
        etag: str | None = None,
    ) -> EventsAPIResponse:
        """Fetch new events for a repository.

        Uses ETag caching: returns empty list with ``has_new_events=False``
        on 304 Not Modified.

        Args:
            owner: Repository owner.
            repo: Repository name.
            installation_id: GitHub App installation ID.
            etag: ETag from a previous poll. If provided, sends
                ``If-None-Match`` header for conditional request.

        Raises:
            GitHubRateLimitError: If rate limited (caller should back off).
            GitHubAppError: On other API errors.
        """
        from syn_adapters.github.client_api import check_response

        path = f"/repos/{owner}/{repo}/events"

        token = await self._client.get_installation_token(installation_id)
        headers: dict[str, str] = {"Authorization": f"Bearer {token}"}

        if etag:
            headers["If-None-Match"] = etag

        response = await self._client._http.get(path, headers=headers)

        poll_interval = int(response.headers.get("X-Poll-Interval", "60"))

        if response.status_code == 304:
            return EventsAPIResponse(
                events=[], poll_interval=poll_interval, has_new_events=False, etag=etag or ""
            )

        if response.status_code == 200:
            return await self._handle_success(response, poll_interval)

        # Handle errors (rate limit, auth, not found, etc.)
        check_response(response)

        # Unreachable if check_response raises, but satisfies type checker
        return EventsAPIResponse(
            events=[], poll_interval=poll_interval, has_new_events=False, etag=etag or ""
        )

    async def _handle_success(
        self,
        response: httpx.Response,
        poll_interval: int,
    ) -> EventsAPIResponse:
        """Process a 200 OK response: extract ETag, paginate, return events."""
        response_etag = response.headers.get("ETag", "")

        data = response.json()
        events: list[GitHubEventPayload] = data if isinstance(data, list) else []

        # Fetch remaining pages (GitHub returns max 30/page, up to 10 pages)
        auth_header = response.request.headers.get("Authorization", "")
        link_header = response.headers.get("Link", "")
        extra = await self._fetch_remaining_pages(link_header, auth_header)
        events.extend(extra)

        return EventsAPIResponse(
            events=events,
            poll_interval=poll_interval,
            has_new_events=bool(events),
            etag=response_etag,
        )

    async def _fetch_remaining_pages(
        self,
        link_header: str,
        auth_header: str,
    ) -> list[GitHubEventPayload]:
        """Follow pagination links to collect all events."""
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
        """Fetch a single pagination page. Returns (events, next_url) or (None, None) on failure."""
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
