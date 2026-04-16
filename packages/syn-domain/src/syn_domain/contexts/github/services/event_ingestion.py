"""GitHub event ingestion application service (ADR-060 Layers 2 + 4).

Domain-owned ingestion logic for the GitHub bounded context. Replaces
the old ``apps/syn-api/services/github_event_poller.py`` shim. Two
classes:

- ``GitHubRepoIngestionService(HistoricalPoller)`` -- per-repo, cold-start
  -safe, HWM-filtering ingestion. Subclasses ESP's ``HistoricalPoller``
  so the cold-start fence (Layer 3) and ``is_replay`` propagation
  (Layer 4) come for free. Adds Layer 2 HWM filtering inside
  ``fetch()`` so warm-start re-delivery of historical events
  (the #694 root cause) is rejected before ``process()`` ever sees them.

- ``GitHubEventIngestionScheduler`` -- the outer loop. Adaptive
  intervals (active polling vs safety net), trigger-store gated
  repo discovery, rate-limit aware backoff, lifecycle.

All adapter dependencies enter through domain ports
(``GitHubEventsAPIPort``). The composition root in ``apps/syn-api/_wiring.py``
binds the concrete adapter to the port.

See ADR-060 Section 9 for the eight-layer defense in depth.
"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from event_sourcing.core.historical_poller import (
    HistoricalPoller,
    PollEvent,
    PollResult,
)

from syn_domain.contexts.github import PollerState, map_events_api_to_normalized
from syn_domain.contexts.github.services.github_events_cursor import GitHubEventsCursor

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

    from event_sourcing.core.historical_poller import CursorStore

    from syn_domain.contexts.github._shared.trigger_query_store import TriggerQueryStore
    from syn_domain.contexts.github.ports import (
        GitHubEventsAPIPort,
    )
    from syn_domain.contexts.github.services.webhook_health import WebhookHealthTracker
    from syn_domain.contexts.github.slices.event_pipeline.pipeline import EventPipeline
    from syn_shared.settings.polling import PollingSettings

logger = logging.getLogger(__name__)


def _parse_event_timestamp(raw_event: dict[str, Any]) -> datetime:
    """Parse created_at from a raw Events API payload into a UTC datetime."""
    created_at = raw_event.get("created_at", "")
    if created_at and created_at.endswith("Z"):
        created_at = created_at[:-1] + "+00:00"
    if created_at:
        return datetime.fromisoformat(created_at)
    return datetime.now(UTC)


def _id_gt(a: str, b: str) -> bool:
    """Compare GitHub event IDs (numeric strings) as integers."""
    try:
        return int(a) > int(b)
    except (TypeError, ValueError):
        return False


# ---------------------------------------------------------------------------
# Per-repo ingestion service (HistoricalPoller subclass)
# ---------------------------------------------------------------------------


class GitHubRepoIngestionService(HistoricalPoller):
    """Per-repo, port-typed, HWM-filtering, cold-start-safe ingestion.

    Subclasses ``HistoricalPoller`` so cold-start fence (Layer 3) and
    ``is_replay`` propagation (Layer 4) come for free. Adds Layer 2
    HWM filtering inside ``fetch()`` so warm-start re-delivery of
    historical events (the #694 root cause) is rejected.
    """

    def __init__(
        self,
        events_api: GitHubEventsAPIPort,
        pipeline: EventPipeline,
        cursor_store: CursorStore,
    ) -> None:
        super().__init__(cursor_store)
        self._events_api = events_api
        self._pipeline = pipeline
        self._installation_ids: dict[str, str] = {}
        self._high_water_marks: dict[str, GitHubEventsCursor] = {}
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
        """Seconds the adapter asked us to wait after the last rate-limit hit."""
        return self._last_rate_limit_wait

    async def initialize(self) -> None:
        """Load persisted cursors AND seed the in-memory HWM cache.

        Critical for the cold->crash->warm scenario: the cold-start poll
        primed the cursor with ``last_event_id`` but then crashed before
        the next steady-state poll. On restart, without HWM seeding, the
        warm-start poll would have no HWM to filter against and would
        re-deliver everything (#694 again).
        """
        await super().initialize()
        cursors = await self._cursor_store.load_all()
        for source_key, raw in cursors.items():
            self._high_water_marks[source_key] = GitHubEventsCursor.from_cursor_data(raw)
        if self._high_water_marks:
            logger.info(
                "Seeded HWM cache for %d source(s) from persisted cursors",
                len(self._high_water_marks),
            )

    async def fetch(self, source_key: str) -> PollResult:
        """Fetch events from GitHub, applying Layer 2 HWM filter.

        Re-delivered historical events (id <= cursor.last_event_id) are
        dropped here, BEFORE ``process()`` sees them. This is the primary
        fix for #694: GitHub's ETag is "anything changed?" not "what
        changed?", so a warm-start re-delivery returns the full recent
        list (up to 300 events). Without an HWM filter the pipeline
        would flood.
        """
        inst_id = self._installation_ids.get(source_key, "")
        owner, repo = source_key.split("/", 1)

        cursor = self._high_water_marks.get(
            source_key,
            GitHubEventsCursor(etag="", last_event_id=""),
        )

        result = await self._events_api.fetch_repo_events(
            owner,
            repo,
            inst_id,
            etag=cursor.etag or None,
        )

        if result.rate_limited:
            self._last_rate_limit_wait = result.retry_after_seconds
            return PollResult(
                events=[],
                cursor=cursor.to_cursor_data(),
                has_new=False,
            )
        self._last_rate_limit_wait = 0.0
        self._last_poll_interval = result.poll_interval_hint

        # LAYER 2: HWM filter. Re-delivered historical events (id <= HWM)
        # are dropped here, BEFORE process() sees them.
        new_events: list[PollEvent] = []
        max_seen = cursor.last_event_id
        for raw in reversed(result.events):  # reversed = oldest-first
            event_id = str(raw.get("id", ""))
            if not cursor.is_newer_than(event_id):
                continue
            new_events.append(
                PollEvent(created_at=_parse_event_timestamp(raw), data=raw),
            )
            if not max_seen or _id_gt(event_id, max_seen):
                max_seen = event_id

        new_cursor = GitHubEventsCursor(etag=result.etag, last_event_id=max_seen)
        # Update in-memory cache so subsequent fetch() in the same poll
        # cycle (multi-repo) sees the latest HWM.
        self._high_water_marks[source_key] = new_cursor

        return PollResult(
            events=new_events,
            cursor=new_cursor.to_cursor_data(),
            has_new=bool(new_events) or result.has_new,
        )

    async def process(
        self,
        source_key: str,
        events: list[PollEvent],
        is_replay: bool = False,
    ) -> None:
        """Normalize events and ingest through the EventPipeline.

        On cold start (``is_replay=True``), events are injected with
        ``source_primed=False`` so the pipeline (Layer 5) skips trigger
        evaluation but still records dedup. ``is_replay`` is the
        authoritative signal from the ESP base class -- the legacy
        ``primed_sources`` check was dead code (ADR-060 §9 Layer 4).
        """
        inst_id = self._installation_ids.get(source_key, "")

        for poll_event in events:
            normalized = map_events_api_to_normalized(poll_event.data, inst_id)
            if normalized is None:
                continue

            if is_replay:
                normalized = dataclasses.replace(normalized, source_primed=False)

            try:
                await self._pipeline.ingest(normalized)
            except Exception:
                logger.exception(
                    "Failed to ingest polled event %s",
                    poll_event.data.get("id"),
                )


# ---------------------------------------------------------------------------
# Outer scheduler (adaptive intervals, trigger store, lifecycle)
# ---------------------------------------------------------------------------


class GitHubEventIngestionScheduler:
    """Background scheduler that drives ``GitHubRepoIngestionService``.

    Runs as an ``asyncio.Task`` inside syn-api -- no new container needed.
    Adapts polling cadence based on webhook health (active vs safety net)
    and honors rate-limit backoff signals from the per-repo service.
    """

    def __init__(
        self,
        repo_service: GitHubRepoIngestionService,
        health_tracker: WebhookHealthTracker,
        trigger_store: TriggerQueryStore,
        settings: PollingSettings,
        sleep: Callable[[float], Coroutine[object, object, None]] | None = None,
    ) -> None:
        self._repo = repo_service
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

        Calls ``repo_service.initialize()`` to load persisted cursors
        and seed the HWM cache before the first poll.
        """
        await self._repo.initialize()
        self._task = asyncio.create_task(self._poll_loop(), name="github-event-poller")
        logger.info("GitHub event ingestion scheduler started")

    async def stop(self) -> None:
        """Stop the polling background task gracefully."""
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
            logger.info("GitHub event ingestion scheduler stopped")

    @property
    def is_running(self) -> bool:
        """Whether the polling task is currently active."""
        return self._task is not None and not self._task.done()

    async def _poll_loop(self) -> None:
        """Main polling loop -- runs until cancelled."""
        while True:
            interval = await self._run_poll_cycle()
            await self._sleep(interval)

    async def _run_poll_cycle(self) -> float:
        """One polling cycle. Returns the sleep interval before the next cycle."""
        self._state.update_mode(webhook_stale=self._health.is_stale)
        interval = self._state.current_interval
        try:
            interval = await self._poll_all_repos(interval)
        except asyncio.CancelledError:
            raise
        except Exception:
            self._state.record_error()
            logger.exception("Polling error, backing off")
            return interval
        return self._apply_rate_limit_backoff(interval)

    def _apply_rate_limit_backoff(self, interval: float) -> float:
        """Stretch the next-sleep interval if the inner fetch was rate-limited."""
        rate_limit_wait = self._repo.last_rate_limit_wait
        if rate_limit_wait > 0.0:
            backoff = max(interval, rate_limit_wait)
            logger.warning("Rate limited during polling, backing off %.0fs", backoff)
            return backoff
        self._state.record_success()
        return interval

    async def _poll_all_repos(self, interval: float) -> float:
        """Poll all repos with active triggers, returning the effective interval."""
        repos = await self._get_repos_to_poll()
        if repos:
            logger.debug(
                "Polling %d repo(s) in %s mode",
                len(repos),
                self._state.mode.value,
            )

        self._repo.set_installation_ids(dict(repos))

        for repo_full_name, _ in repos:
            if "/" not in repo_full_name:
                logger.warning("Skipping malformed repo name: %s", repo_full_name)
                continue
            await self._repo.poll(repo_full_name)

        return interval

    async def _get_repos_to_poll(self) -> list[tuple[str, str]]:
        """Get (repo, installation_id) pairs for repos with active triggers."""
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
