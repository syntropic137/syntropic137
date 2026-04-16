"""Check-run poller — poll-based self-healing without webhooks (#602).

When a pull_request event arrives (via Events API or webhook), the pipeline
observer registers the head SHA. This poller periodically checks the GitHub
Checks API for those SHAs. When a check run completes with failure, it
synthesizes a check_run.completed NormalizedEvent and feeds it through the
EventPipeline, triggering self-healing workflows.

Runs as an ``asyncio.Task`` inside syn-api alongside the Events API poller.
Adapts its polling interval based on webhook health (30s when stale, 120s
when healthy — webhooks deliver check_run events faster).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from syn_domain.contexts.github import PendingSHA, PollerState, synthesize_check_run_event

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

    from syn_api.services.webhook_health_tracker import WebhookHealthTracker
    from syn_domain.contexts.github._shared.trigger_query_store import TriggerQueryStore
    from syn_domain.contexts.github.slices.event_pipeline.normalized_event import NormalizedEvent
    from syn_domain.contexts.github.slices.event_pipeline.pending_sha_port import PendingSHAStore
    from syn_domain.contexts.github.slices.event_pipeline.pipeline import EventPipeline
    from syn_domain.contexts.github.slices.event_pipeline.ports import GitHubChecksAPIPort
    from syn_shared.settings.polling import PollingSettings

logger = logging.getLogger(__name__)


class CheckRunPoller:
    """Background poller that detects CI failures via the GitHub Checks API.

    Works in concert with the Events API poller and webhooks:
    - Webhooks deliver ``check_run.completed`` in ~1s (when configured)
    - This poller synthesizes equivalent events in 30-90s (zero-config)
    - Content-based dedup ensures only one trigger fire regardless of source
    """

    def __init__(
        self,
        checks_client: GitHubChecksAPIPort,
        pipeline: EventPipeline,
        sha_store: PendingSHAStore,
        health_tracker: WebhookHealthTracker,
        trigger_store: TriggerQueryStore,
        settings: PollingSettings,
        sleep: Callable[[float], Coroutine[object, object, None]] | None = None,
    ) -> None:
        self._checks_client = checks_client
        self._pipeline = pipeline
        self._sha_store = sha_store
        self._health = health_tracker
        self._trigger_store = trigger_store
        self._settings = settings
        self._state = PollerState(
            base_interval=settings.check_run_poll_interval_seconds,
            safety_interval=settings.check_run_safety_interval_seconds,
        )
        self._task: asyncio.Task[None] | None = None
        self._sleep = sleep or asyncio.sleep

    async def start(self) -> None:
        """Start the check-run polling background task."""
        if self.is_running:
            logger.info("Check-run poller already running; start() ignored")
            return
        self._task = asyncio.create_task(self._poll_loop(), name="check-run-poller")
        logger.info("Check-run poller started")

    async def stop(self) -> None:
        """Stop the check-run polling background task gracefully."""
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
            logger.info("Check-run poller stopped")

    @property
    def is_running(self) -> bool:
        """Whether the polling task is currently active."""
        return self._task is not None and not self._task.done()

    async def on_pr_event(self, event: NormalizedEvent) -> None:
        """Pipeline observer callback — registers pending SHAs for PR events.

        Called by EventPipeline after each non-deduplicated event. Only acts
        on pull_request events with actions that indicate new code to check.
        """
        if event.event_type != "pull_request":
            return
        if event.action not in ("opened", "synchronize", "reopened"):
            return

        pr = event.payload.get("pull_request", {})
        head = pr.get("head", {})
        sha: str = head.get("sha", "")
        branch: str = head.get("ref", "")
        pr_number: int = event.payload.get("number") or pr.get("number", 0)

        if not sha or not pr_number:
            logger.debug("PR event missing sha or number, skipping: %s", event.dedup_key)
            return

        pending = PendingSHA(
            repository=event.repository,
            sha=sha,
            pr_number=pr_number,
            branch=branch,
            installation_id=event.installation_id,
            registered_at=datetime.now(UTC),
        )
        await self._sha_store.register(pending)
        logger.debug(
            "Registered pending SHA %s for %s PR #%d",
            sha[:8],
            event.repository,
            pr_number,
        )

    # -- Internal polling loop -----------------------------------------------

    async def _poll_loop(self) -> None:
        """Main polling loop — runs until cancelled."""
        while True:
            self._state.update_mode(webhook_stale=self._health.is_stale)
            interval = self._state.current_interval

            try:
                if await self._has_check_run_triggers():
                    await self._poll_pending_shas()
                await self._cleanup_stale_shas()
                self._state.record_success()
            except asyncio.CancelledError:
                raise
            except Exception:
                self._state.record_error()
                logger.exception("Check-run polling error, backing off")

            await self._sleep(interval)

    async def _has_check_run_triggers(self) -> bool:
        """Check if any active triggers listen for check_run events."""
        all_triggers = await self._trigger_store.list_all(status="active")
        return any("check_run" in getattr(t, "event", "") for t in all_triggers)

    async def _poll_pending_shas(self) -> None:
        """Poll the Checks API for each pending SHA."""
        pending_list = await self._sha_store.list_pending()
        if not pending_list:
            return

        logger.debug("Polling check runs for %d pending SHA(s)", len(pending_list))

        for pending in pending_list:
            try:
                await self._poll_single_sha(pending)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception(
                    "Failed to poll check runs for %s@%s",
                    pending.repository,
                    pending.sha[:8],
                )

    async def _poll_single_sha(self, pending: PendingSHA) -> None:
        """Poll check runs for a single SHA and synthesize events for failures."""
        if "/" not in pending.repository:
            logger.warning("Invalid repository format (no '/'): %s", pending.repository)
            return
        owner, repo = pending.repository.split("/", 1)
        result = await self._checks_client.fetch_check_runs(
            owner=owner,
            repo=repo,
            ref=pending.sha,
            installation_id=pending.installation_id,
        )

        if result.rate_limited:
            self._state.record_error()
            logger.warning(
                "Check-run poller rate limited, backing off %.0fs",
                result.retry_after_seconds,
            )
            return

        all_completed = True
        for raw_check_run in result.check_runs:
            if raw_check_run.get("status") != "completed":
                all_completed = False
                continue
            await self._ingest_synthesized_event(raw_check_run, pending)

        if all_completed and result.check_runs:
            await self._sha_store.remove(pending.repository, pending.sha)
            logger.debug(
                "All check runs completed for %s@%s, removed from pending",
                pending.repository,
                pending.sha[:8],
            )

    async def _ingest_synthesized_event(
        self, raw_check_run: dict[str, object], pending: PendingSHA
    ) -> None:
        """Synthesize a check_run event and feed it through the pipeline."""
        event = synthesize_check_run_event(raw_check_run, pending)
        if event is None:
            return
        try:
            result = await self._pipeline.ingest(event)
            if result.status == "processed" and result.triggers_fired:
                logger.info(
                    "Synthesized check_run.completed for %s@%s — fired %s",
                    pending.repository,
                    pending.sha[:8],
                    result.triggers_fired,
                )
        except Exception:
            logger.exception(
                "Failed to ingest synthesized check_run event for %s@%s",
                pending.repository,
                pending.sha[:8],
            )

    async def _cleanup_stale_shas(self) -> None:
        """Remove SHAs that have exceeded the TTL (e.g., abandoned PRs)."""
        max_age = timedelta(seconds=self._settings.check_run_sha_ttl_seconds)
        removed = await self._sha_store.cleanup_stale(max_age)
        if removed:
            logger.info("Cleaned up %d stale pending SHA(s)", removed)

