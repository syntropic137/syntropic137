"""GitHubEventsAPIPort - domain-owned contract for the GitHub Events API.

Implementations live in ``packages/syn-adapters/github/``. The domain depends
only on this Protocol, preserving hexagonal boundaries.

Translation responsibilities of the adapter:

- Hide HTTP details (status codes, headers, ETag, retries, pagination).
- Translate ``GitHubRateLimitError`` into ``rate_limited`` + ``retry_after``
  fields. The port is total -- no exception types leak into the domain.
- Preserve raw event payloads as ``dict[str, Any]`` (the
  ``event_type_mapper`` consumes them).
- Honor ``X-Poll-Interval`` as ``poll_interval_hint``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

GitHubEventPayload = dict[str, Any]
"""Raw GitHub event payload (heterogeneous JSON, mapped by event_type_mapper)."""


@dataclass(frozen=True, slots=True)
class EventsAPIResult:
    """Result of a single Events API poll.

    The adapter handles 304 Not Modified (returns ``has_new=False``,
    ``events=[]``, ``etag=existing``) and pagination (returns the full
    collected list).
    """

    events: list[GitHubEventPayload]
    """Raw event payloads, newest-first as returned by GitHub."""

    has_new: bool
    """``False`` on HTTP 304 Not Modified. When ``False``, ``events`` is empty."""

    etag: str
    """ETag from response. Persisted by the caller for the next conditional request."""

    poll_interval_hint: int
    """``X-Poll-Interval`` header value (seconds). Caller should not poll faster."""

    rate_limited: bool = False
    """``True`` if GitHub returned a rate-limit error. Caller should back off."""

    retry_after_seconds: float = 0.0
    """When ``rate_limited=True``, seconds the caller should wait before retry.

    Computed from the ``X-RateLimit-Reset`` header when available; falls back
    to a 60-second conservative default.
    """


class GitHubEventsAPIPort(Protocol):
    """Port: fetches events for a single repo from the GitHub Events API.

    Stateless from the domain's perspective -- the cursor (etag) is owned by
    the domain (``GitHubEventsCursor``) and passed in on every call.
    """

    async def fetch_repo_events(
        self,
        owner: str,
        repo: str,
        installation_id: str,
        etag: str | None = None,
    ) -> EventsAPIResult:
        """Fetch events for a repository.

        On rate-limit, returns ``EventsAPIResult(rate_limited=True,
        retry_after_seconds=N, events=[], has_new=False, etag=etag or "",
        poll_interval_hint=60)``. The adapter does NOT raise.
        """
        ...
