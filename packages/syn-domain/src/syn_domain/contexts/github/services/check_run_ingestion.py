"""Check-run ingestion application service (#602).

Poll-based self-healing pipeline. Listens for PR events via the
EventPipeline observer hook, registers head SHAs, polls the GitHub
Checks API per pending SHA, synthesizes ``check_run.completed`` events
on completion, and ingests them through the unified pipeline.

This service is reactive (not historical) -- it only polls SHAs that
arrived from PR events ingested by ``GitHubRepoIngestionService``. The
cold-start protection is transitive: PR events from cold-start carry
``source_primed=False`` so the pipeline (Layer 5) skips trigger eval.
The principal #694 fix lives in the upstream ingestion service; this
service depends only on Protocols (``GitHubChecksAPIPort``) so the
hexagonal boundary is preserved.
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

    from syn_domain.contexts.github._shared.trigger_query_store import TriggerQueryStore
    from syn_domain.contexts.github.ports import GitHubChecksAPIPort
    from syn_domain.contexts.github.services.webhook_health import WebhookHealthTracker
    from syn_domain.contexts.github.slices.event_pipeline.normalized_event import NormalizedEvent
    from syn_domain.contexts.github.slices.event_pipeline.pending_sha_port import PendingSHAStore
    from syn_domain.contexts.github.slices.event_pipeline.pipeline import EventPipeline
    from syn_shared.settings.polling import PollingSettings

logger = logging.getLogger(__name__)


class CheckRunIngestionService:
    """Background poller that detects CI failures via the GitHub Checks API.

    Works in concert with the Events API poller and webhooks:

    - Webhooks deliver ``check_run.completed`` in ~1s (when configured)
    - This poller synthesizes equivalent events in 30-90s (zero-config)
    - Content-based dedup ensures one trigger fire regardless of source
    """

    def __init__(
        self,
        checks_api: GitHubChecksAPIPort,
        pipeline: EventPipeline,
        sha_store: PendingSHAStore,
        health_tracker: WebhookHealthTracker,
        trigger_store: TriggerQueryStore,
        settings: PollingSettings,
        sleep: Callable[[float], Coroutine[object, object, None]] | None = None,
    ) -> None:
        self._checks_api = checks_api
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
        self._last_rate_limit_wait: float = 0.0

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
        """Pipeline observer callback -- registers pending SHAs for PR events.

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

    async def _poll_loop(self) -> None:
        """Main polling loop -- runs until cancelled."""
        while True:
            self._state.update_mode(webhook_stale=self._health.is_stale)
            interval = self._state.current_interval
            self._last_rate_limit_wait = 0.0

            try:
                if await self._has_check_run_triggers():
                    await self._poll_pending_shas()
                await self._cleanup_stale_shas()
                if self._last_rate_limit_wait == 0.0:
                    self._state.record_success()
            except asyncio.CancelledError:
                raise
            except Exception:
                self._state.record_error()
                logger.exception("Check-run polling error, backing off")

            sleep_for = max(interval, self._last_rate_limit_wait)
            await self._sleep(sleep_for)

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
        result = await self._checks_api.fetch_check_runs(
            owner=owner,
            repo=repo,
            ref=pending.sha,
            installation_id=pending.installation_id,
        )

        if result.rate_limited:
            self._state.record_error()
            self._last_rate_limit_wait = max(self._last_rate_limit_wait, result.retry_after_seconds)
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
                    "Synthesized check_run.completed for %s@%s -- fired %s",
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
