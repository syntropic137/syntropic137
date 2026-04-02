"""GitHub Events API poller — background task for hybrid event ingestion (ISS-386).

Polls the GitHub Events API for repositories that have active triggers,
feeding events through the unified EventPipeline. Adapts its polling
interval based on webhook health (aggressive when webhooks are stale,
lazy when webhooks are healthy).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable, Coroutine
from typing import TYPE_CHECKING

from syn_domain.contexts.github.slices.event_pipeline.event_type_mapper import (
    map_events_api_to_normalized,
)
from syn_domain.contexts.github.slices.event_pipeline.poller_state import PollerState

if TYPE_CHECKING:
    from typing import Any

    from syn_adapters.github.events_api_client import GitHubEventsAPIClient
    from syn_api.services.webhook_health_tracker import WebhookHealthTracker
    from syn_domain.contexts.github._shared.trigger_query_store import TriggerQueryStore
    from syn_domain.contexts.github.slices.event_pipeline.pipeline import EventPipeline
    from syn_shared.settings.polling import PollingSettings

logger = logging.getLogger(__name__)


class GitHubEventPoller:
    """Background poller that feeds GitHub Events API data into the EventPipeline.

    Runs as an ``asyncio.Task`` inside syn-api — no new container needed.
    """

    def __init__(
        self,
        events_client: GitHubEventsAPIClient,
        pipeline: EventPipeline,
        health_tracker: WebhookHealthTracker,
        trigger_store: TriggerQueryStore,
        settings: PollingSettings,
        sleep: Callable[[float], Coroutine[object, object, None]] | None = None,
    ) -> None:
        self._events_client = events_client
        self._pipeline = pipeline
        self._health = health_tracker
        self._trigger_store = trigger_store
        self._state = PollerState(
            base_interval=settings.poll_interval_seconds,
            safety_interval=settings.safety_net_interval_seconds,
        )
        self._task: asyncio.Task[None] | None = None
        self._sleep = sleep or asyncio.sleep

    async def start(self) -> None:
        """Start the polling background task."""
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
        """Main polling loop — runs until cancelled."""
        while True:
            self._state.update_mode(webhook_stale=self._health.is_stale)
            interval = self._state.current_interval

            try:
                interval = await self._poll_all_repos(interval)
                self._state.record_success()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                interval = self._handle_poll_error(exc, interval)

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

        for repo_full_name, installation_id in repos:
            if "/" not in repo_full_name:
                logger.warning("Skipping malformed repo name: %s", repo_full_name)
                continue
            owner, repo = repo_full_name.split("/", 1)
            response = await self._events_client.poll_repo_events(owner, repo, installation_id)
            if response.has_new_events:
                await self._process_events(response.events, installation_id)
            interval = max(interval, response.poll_interval)

        return interval

    def _handle_poll_error(self, exc: Exception, interval: float) -> float:
        """Handle a polling error: record backoff and adjust interval."""
        self._state.record_error()
        reset_seconds = _extract_rate_limit_wait(exc)
        if reset_seconds is not None:
            interval = max(interval, reset_seconds)
            logger.warning("Rate limited during polling, backing off %.0fs", interval)
        else:
            logger.exception("Polling error, backing off")
        return interval

    async def _get_repos_to_poll(self) -> list[tuple[str, str]]:
        """Get (repo, installation_id) pairs for repos with active triggers.

        Only polls repos that have at least one active trigger —
        no wasted API calls for repos without triggers.
        """
        all_triggers = await self._trigger_store.list_all(status="active")
        seen: dict[str, str] = {}
        for t in all_triggers:
            repo: str = t.repository
            if repo and repo not in seen:
                seen[repo] = t.installation_id
        return list(seen.items())

    async def _process_events(self, raw_events: list[dict[str, Any]], installation_id: str) -> None:
        """Map and ingest events. Events API returns newest first, so we reverse."""
        for raw in reversed(raw_events):
            normalized = map_events_api_to_normalized(raw, installation_id)
            if normalized is not None:
                try:
                    await self._pipeline.ingest(normalized)
                except Exception:
                    logger.exception("Failed to ingest polled event %s", raw.get("id"))


def _extract_rate_limit_wait(exc: Exception) -> float | None:
    """Extract wait seconds from a GitHubRateLimitError, if applicable."""
    from datetime import UTC, datetime

    # Avoid importing at module level to keep this file light
    try:
        from syn_adapters.github.client import GitHubRateLimitError
    except ImportError:
        return None

    if isinstance(exc, GitHubRateLimitError) and exc.reset_at is not None:
        wait = (exc.reset_at - datetime.now(UTC)).total_seconds()
        return max(wait, 0)
    return None
