"""GitHub Events API client with ETag caching for efficient polling (ISS-386)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from syn_adapters.github.client import GitHubAppClient

logger = logging.getLogger(__name__)


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

    def __init__(self, github_client: GitHubAppClient) -> None:
        self._client = github_client
        self._etags: dict[str, str] = {}  # repo -> ETag

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
            etag = response.headers.get("ETag", "")
            if etag:
                self._etags[etag_key] = etag

            events: list[dict[str, Any]] = response.json()
            return EventsAPIResponse(
                events=events,
                poll_interval=poll_interval,
                has_new_events=True,
            )

        # Handle errors (rate limit, auth, not found, etc.)
        check_response(response)

        # Unreachable if check_response raises, but satisfies type checker
        return EventsAPIResponse(events=[], poll_interval=poll_interval, has_new_events=False)
