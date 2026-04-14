"""GitHub Events API client with ETag caching for efficient polling (ISS-386).

See ADR-060: Restart-safe trigger deduplication (persistent cursor support).
"""

from __future__ import annotations

import logging
import re as _re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    import httpx

    from syn_adapters.github.client import GitHubAppClient
    from syn_adapters.github.poller_cursor_store import PollerCursor

logger = logging.getLogger(__name__)

# Type alias for raw GitHub event payloads (heterogeneous JSON from Events API).
GitHubEventPayload = dict[str, Any]


class PollerCursorStore(Protocol):
    """Protocol for persisting poller ETag/cursor state across restarts."""

    async def save_cursor(self, repo: str, etag: str, last_event_id: str) -> None: ...
    async def load_cursor(self, repo: str) -> PollerCursor | None: ...
    async def load_all(self) -> dict[str, PollerCursor]: ...


@dataclass(frozen=True, slots=True)
class EventsAPIResponse:
    """Response from a single Events API poll."""

    events: list[GitHubEventPayload]
    poll_interval: int
    """``X-Poll-Interval`` header value (seconds). GitHub recommends this as
    the minimum interval between requests."""
    has_new_events: bool
    """``False`` when GitHub returned 304 Not Modified."""


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
    """Client for GitHub's repository Events API with ETag caching.

    Uses conditional requests (``If-None-Match``) to minimize API calls
    and respects the ``X-Poll-Interval`` header from GitHub.

    See: https://docs.github.com/en/rest/activity/events
    """

    def __init__(
        self,
        github_client: GitHubAppClient,
        cursor_store: PollerCursorStore | None = None,
    ) -> None:
        self._client = github_client
        self._etags: dict[str, str] = {}  # repo -> ETag (in-memory cache)
        self._cursor_store = cursor_store
        self._cursors_loaded = False

    async def poll_repo_events(
        self,
        owner: str,
        repo: str,
        installation_id: str,
    ) -> EventsAPIResponse:
        """Fetch new events for a repository.

        Uses ETag caching: returns empty list with ``has_new_events=False``
        on 304 Not Modified.

        Raises:
            GitHubRateLimitError: If rate limited (caller should back off).
            GitHubAppError: On other API errors.
        """
        from syn_adapters.github.client_api import check_response

        # Load persisted cursors on first poll (ADR-060)
        await self._load_persisted_cursors()

        path = f"/repos/{owner}/{repo}/events"
        etag_key = f"{owner}/{repo}"

        token = await self._client.get_installation_token(installation_id)
        headers: dict[str, str] = {"Authorization": f"Bearer {token}"}

        if etag_key in self._etags:
            headers["If-None-Match"] = self._etags[etag_key]

        response = await self._client._http.get(path, headers=headers)

        poll_interval = int(response.headers.get("X-Poll-Interval", "60"))

        if response.status_code == 304:
            return EventsAPIResponse(events=[], poll_interval=poll_interval, has_new_events=False)

        if response.status_code == 200:
            return await self._handle_success(response, etag_key, poll_interval)

        # Handle errors (rate limit, auth, not found, etc.)
        check_response(response)

        # Unreachable if check_response raises, but satisfies type checker
        return EventsAPIResponse(events=[], poll_interval=poll_interval, has_new_events=False)

    async def _handle_success(
        self,
        response: httpx.Response,
        etag_key: str,
        poll_interval: int,
    ) -> EventsAPIResponse:
        """Process a 200 OK response: cache ETag, persist cursor, return events."""
        etag = response.headers.get("ETag", "")
        if etag:
            self._etags[etag_key] = etag

        data = response.json()
        events: list[GitHubEventPayload] = data if isinstance(data, list) else []

        # Fetch remaining pages (GitHub returns max 30/page, up to 10 pages)
        auth_header = response.request.headers.get("Authorization", "")
        link_header = response.headers.get("Link", "")
        extra = await self._fetch_remaining_pages(link_header, auth_header, etag_key)
        events.extend(extra)

        # Persist cursor for restart safety (ADR-060)
        await self._persist_cursor(etag_key, etag, events)

        return EventsAPIResponse(
            events=events,
            poll_interval=poll_interval,
            has_new_events=bool(events),
        )

    async def _fetch_remaining_pages(
        self,
        link_header: str,
        auth_header: str,
        etag_key: str,
    ) -> list[GitHubEventPayload]:
        """Follow pagination links to collect all events."""
        extra_events: list[GitHubEventPayload] = []
        next_url = _parse_next_link(link_header)
        pages_fetched = 1
        while next_url and pages_fetched < _MAX_PAGES:
            page_events, next_url = await self._fetch_single_page(
                next_url, auth_header, etag_key, pages_fetched + 1
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
        etag_key: str,
        page_number: int,
    ) -> tuple[list[GitHubEventPayload] | None, str | None]:
        """Fetch a single pagination page. Returns (events, next_url) or (None, None) on failure."""
        try:
            resp = await self._client._http.get(
                url, headers={"Authorization": auth_header}
            )
            if resp.status_code != 200:
                logger.warning(
                    "Events API pagination stopped: page %d returned %d for %s",
                    page_number,
                    resp.status_code,
                    etag_key,
                )
                return None, None
            page_data = resp.json()
            if not isinstance(page_data, list) or not page_data:
                return None, None
            return page_data, _parse_next_link(resp.headers.get("Link", ""))
        except Exception:
            logger.warning(
                "Failed to fetch events page %d for %s",
                page_number,
                etag_key,
                exc_info=True,
            )
            return None, None

    async def _persist_cursor(self, etag_key: str, etag: str, events: list[GitHubEventPayload]) -> None:
        """Persist ETag cursor for restart safety (ADR-060)."""
        if not etag or self._cursor_store is None:
            return
        newest_id = str(events[0].get("id", "")) if events else ""
        try:
            await self._cursor_store.save_cursor(etag_key, etag, newest_id)
        except Exception:
            logger.warning("Failed to persist poller cursor for %s", etag_key, exc_info=True)

    async def _load_persisted_cursors(self) -> None:
        """Load ETags from persistent store on first call (ADR-060)."""
        if self._cursors_loaded or self._cursor_store is None:
            return
        self._cursors_loaded = True
        try:
            cursors = await self._cursor_store.load_all()
            for repo, cursor in cursors.items():
                etag = getattr(cursor, "etag", "")
                if etag:
                    self._etags[repo] = etag
            logger.info("Loaded %d persisted ETag(s) from cursor store", len(cursors))
        except Exception:
            logger.warning(
                "Failed to load persisted cursors — polling will re-fetch", exc_info=True
            )
