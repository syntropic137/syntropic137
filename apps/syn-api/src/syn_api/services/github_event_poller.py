"""GitHub Events API poller -- background task for hybrid event ingestion (ISS-386).

Architecture: composition of two classes:

- ``GitHubRepoPoller(HistoricalPoller)`` -- per-repo cold-start-safe polling.
  Extends ESP's HistoricalPoller base class so the cold-start fence is
  structural and non-bypassable (``poll()`` is ``@final``).

- ``GitHubEventPoller`` -- outer loop that manages adaptive intervals,
  trigger store queries, rate-limit backoff, and background task lifecycle.
  Calls ``GitHubRepoPoller.poll(source_key)`` for each repo.

See ADR-060: Restart-safe trigger deduplication (cold-start fence).
"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from event_sourcing.core.historical_poller import (
    CursorData,
    HistoricalPoller,
    PollEvent,
    PollResult,
)

from syn_domain.contexts.github import PollerState, map_events_api_to_normalized

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine
    from typing import Any

    from event_sourcing.core.historical_poller import CursorStore

    from syn_api.services.webhook_health_tracker import WebhookHealthTracker
    from syn_domain.contexts.github._shared.trigger_query_store import TriggerQueryStore
    from syn_domain.contexts.github.slices.event_pipeline.pipeline import EventPipeline
    from syn_domain.contexts.github.slices.event_pipeline.ports import GitHubEventsAPIPort
    from syn_shared.settings.polling import PollingSettings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Timestamp parsing
# ---------------------------------------------------------------------------


def _parse_event_timestamp(raw_event: dict[str, Any]) -> datetime:
    """Parse created_at from a raw Events API payload into a UTC datetime."""
    created_at = raw_event.get("created_at", "")
    if created_at and created_at.endswith("Z"):
        created_at = created_at[:-1] + "+00:00"
    if created_at:
        return datetime.fromisoformat(created_at)
    return datetime.now(UTC)


# ---------------------------------------------------------------------------
# GitHubRepoPoller -- per-repo, cold-start-safe (HistoricalPoller subclass)
# ---------------------------------------------------------------------------


class GitHubRepoPoller(HistoricalPoller):
    """Per-repo poller with cold-start safety via HistoricalPoller.

    ``fetch()`` calls the GitHub Events API client and maps the response
    to ``PollResult``. ``process()`` normalizes events and ingests them
    through the ``EventPipeline``.

    On cold start (no persisted cursor), historical events are filtered
    by the base class ``poll()`` method. Events that pass the fence are
    ingested with ``source_primed=False`` as a belt-and-suspenders check
    (the pipeline skips trigger evaluation for unprimed events).
    """

    def __init__(
        self,
        events_client: GitHubEventsAPIPort,
        pipeline: EventPipeline,
        cursor_store: CursorStore,
    ) -> None:
        super().__init__(cursor_store)
        self._events_client = events_client
        self._pipeline = pipeline
        self._installation_ids: dict[str, str] = {}
        self._last_poll_interval: int | None = None
        self._last_rate_limit_wait: float = 0.0

    def set_installation_ids(self, mapping: dict[str, str]) -> None:
        """Update repo -> installation_id mapping for the current poll cycle."""
        self._installation_ids = mapping

    @property
    def last_poll_interval(self) -> int | None:
        """GitHub's recommended poll interval from the last response, if any."""
        return self._last_poll_interval

    @property
    def last_rate_limit_wait(self) -> float:
        """Seconds the adapter asked us to wait after the last rate-limit hit (0.0 = none)."""
        return self._last_rate_limit_wait

    async def fetch(self, source_key: str) -> PollResult:
        """Fetch events from the GitHub Events API for one repository.

        Loads the stored ETag from the cursor store and passes it to the
        port for conditional requests (If-None-Match). Returns a
        ``PollResult`` with events ordered oldest-first.
        """
        inst_id = self._installation_ids.get(source_key, "")
        owner, repo = source_key.split("/", 1)

        # Load stored ETag from cursor (set by HistoricalPoller on previous poll)
        stored_cursor = await self._cursor_store.load(source_key)
        stored_etag = stored_cursor.value if stored_cursor else None

        result = await self._events_client.fetch_repo_events(
            owner,
            repo,
            inst_id,
            etag=stored_etag,
        )

        if result.rate_limited:
            self._last_rate_limit_wait = result.retry_after_seconds
            return PollResult(
                events=[],
                cursor=stored_cursor or CursorData(value=stored_etag or "", metadata={}),
                has_new=False,
            )
        self._last_rate_limit_wait = 0.0
        self._last_poll_interval = result.poll_interval_hint

        # Map raw events to PollEvent (reversed: Events API returns newest-first)
        poll_events: list[PollEvent] = []
        for raw in reversed(result.events):
            created_at = _parse_event_timestamp(raw)
            poll_events.append(PollEvent(created_at=created_at, data=raw))

        # Build cursor from response ETag + newest event ID
        newest_id = str(result.events[0].get("id", "")) if result.events else ""
        cursor = CursorData(
            value=result.etag,
            metadata={"last_event_id": newest_id},
        )

        return PollResult(events=poll_events, cursor=cursor, has_new=result.has_new)

    async def process(self, source_key: str, events: list[PollEvent]) -> None:
        """Normalize events and ingest through the EventPipeline.

        On cold start, events are injected with ``source_primed=False``
        so the pipeline skips trigger evaluation (belt-and-suspenders
        with the HistoricalPoller timestamp fence).
        """
        inst_id = self._installation_ids.get(source_key, "")
        is_primed = source_key in self.primed_sources

        for poll_event in events:
            normalized = map_events_api_to_normalized(poll_event.data, inst_id)
            if normalized is None:
                continue

            # Cold-start events get source_primed=False as a safety net
            if not is_primed:
                normalized = dataclasses.replace(normalized, source_primed=False)

            try:
                await self._pipeline.ingest(normalized)
            except Exception:
                logger.exception(
                    "Failed to ingest polled event %s",
                    poll_event.data.get("id"),
                )


# ---------------------------------------------------------------------------
# GitHubEventPoller -- outer loop (adaptive intervals, trigger store, lifecycle)
# ---------------------------------------------------------------------------


class GitHubEventPoller:
    """Background poller that feeds GitHub Events API data into the EventPipeline.

    Runs as an ``asyncio.Task`` inside syn-api -- no new container needed.
    Delegates per-repo polling to ``GitHubRepoPoller(HistoricalPoller)``
    for cold-start safety.
    """

    def __init__(
        self,
        repo_poller: GitHubRepoPoller,
        health_tracker: WebhookHealthTracker,
        trigger_store: TriggerQueryStore,
        settings: PollingSettings,
        sleep: Callable[[float], Coroutine[object, object, None]] | None = None,
    ) -> None:
        self._repo_poller = repo_poller
        self._health = health_tracker
        self._trigger_store = trigger_store
        self._state = PollerState(
            base_interval=settings.poll_interval_seconds,
            safety_interval=settings.safety_net_interval_seconds,
        )
        self._task: asyncio.Task[None] | None = None
        self._sleep = sleep or asyncio.sleep

    async def start(self) -> None:
        """Start the polling background task.

        Calls ``repo_poller.initialize()`` to load persisted cursors
        before starting the poll loop.
        """
        await self._repo_poller.initialize()
        self._task = asyncio.create_task(self._poll_loop(), name="github-event-poller")
        logger.info("GitHub event poller started")

    async def stop(self) -> None:
        """Stop the polling background task gracefully."""
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
            logger.info("GitHub event poller stopped")

    @property
    def is_running(self) -> bool:
        """Whether the polling task is currently active."""
        return self._task is not None and not self._task.done()

    async def _poll_loop(self) -> None:
        """Main polling loop -- runs until cancelled."""
        while True:
            self._state.update_mode(webhook_stale=self._health.is_stale)
            interval = self._state.current_interval

            try:
                interval = await self._poll_all_repos(interval)
                # Port surfaces rate-limit as a result field; honor the wait it asked for.
                if self._repo_poller.last_rate_limit_wait > 0.0:
                    interval = max(interval, self._repo_poller.last_rate_limit_wait)
                    logger.warning(
                        "Rate limited during polling, backing off %.0fs", interval
                    )
                else:
                    self._state.record_success()
            except asyncio.CancelledError:
                raise
            except Exception:
                self._state.record_error()
                logger.exception("Polling error, backing off")

            await self._sleep(interval)

    async def _poll_all_repos(self, interval: float) -> float:
        """Poll all repos with active triggers, returning the effective interval."""
        repos = await self._get_repos_to_poll()
        if repos:
            logger.debug(
                "Polling %d repo(s) in %s mode",
                len(repos),
                self._state.mode.value,
            )

        # Update installation ID mapping for this cycle
        self._repo_poller.set_installation_ids(dict(repos))

        for repo_full_name, _ in repos:
            if "/" not in repo_full_name:
                logger.warning("Skipping malformed repo name: %s", repo_full_name)
                continue
            # HistoricalPoller.poll() is @final -- cold-start fence is enforced
            await self._repo_poller.poll(repo_full_name)

        return interval

    async def _get_repos_to_poll(self) -> list[tuple[str, str]]:
        """Get (repo, installation_id) pairs for repos with active triggers.

        Only polls repos that have at least one active trigger --
        no wasted API calls for repos without triggers.
        """
        all_triggers = await self._trigger_store.list_all(status="active")
        seen: dict[str, str] = {}
        for t in all_triggers:
            repo: str = t.repository
            if not repo or repo in seen:
                continue
            inst_id = t.installation_id.strip() if t.installation_id else ""
            if not inst_id:
                logger.debug("Skipping repo %s: no installation_id configured", repo)
                continue
            seen[repo] = inst_id
        return list(seen.items())


