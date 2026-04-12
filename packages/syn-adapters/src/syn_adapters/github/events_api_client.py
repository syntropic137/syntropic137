"""GitHub Events API client with ETag caching for efficient polling (ISS-386).

See ADR-060: Restart-safe trigger deduplication (persistent cursor support).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    import httpx

    from syn_adapters.github.client import GitHubAppClient
    from syn_adapters.github.poller_cursor_store import PollerCursor

logger = logging.getLogger(__name__)


class PollerCursorStore(Protocol):
    """Protocol for persisting poller ETag/cursor state across restarts."""

    async def save_cursor(self, repo: str, etag: str, last_event_id: str) -> None: ...
    async def load_cursor(self, repo: str) -> PollerCursor | None: ...
    async def load_all(self) -> dict[str, PollerCursor]: ...


@dataclass(frozen=True, slots=True)
class EventsAPIResponse:
    """Response from a single Events API poll."""

    events: list[dict[str, Any]]
    poll_interval: int
    """``X-Poll-Interval`` header value (seconds). GitHub recommends this as
    the minimum interval between requests."""
    has_new_events: bool
    """``False`` when GitHub returned 304 Not Modified."""


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
        events: list[dict[str, Any]] = data if isinstance(data, list) else []

        # Persist cursor for restart safety (ADR-060)
        if etag and self._cursor_store is not None:
            newest_id = str(events[0].get("id", "")) if events else ""
            try:
                await self._cursor_store.save_cursor(etag_key, etag, newest_id)
            except Exception:
                logger.warning("Failed to persist poller cursor for %s", etag_key, exc_info=True)

        return EventsAPIResponse(
            events=events,
            poll_interval=poll_interval,
            has_new_events=bool(events),
        )

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
