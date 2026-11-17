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
from syn_domain.contexts.github.ports import PullRequestReadiness
from syn_domain.contexts.github.slices.event_pipeline.check_run_synthesizer import (
    rescope_after_ready_for_review,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

    from syn_domain.contexts.github._shared.trigger_query_store import TriggerQueryStore
    from syn_domain.contexts.github.ports import GitHubChecksAPIPort, PullRequestDraftPort
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
        draft_state: PullRequestDraftPort,
        sleep: Callable[[float], Coroutine[object, object, None]] | None = None,
    ) -> None:
        self._checks_api = checks_api
        self._draft_state = draft_state
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
        on pull_request events with actions that indicate new code to check,
        or a draft marked ready for review, whose failed checks were held back
        while it was a draft and are re-checked now (#2058).
        """
        if event.event_type != "pull_request":
            return
        if event.action not in ("opened", "synchronize", "reopened", "ready_for_review"):
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
        if event.action == "ready_for_review" and await self._has_check_run_triggers():
            await self._recheck_after_ready_for_review(pending)

    async def _recheck_after_ready_for_review(self, pending: PendingSHA) -> None:
        """Re-ingest the head SHA's completed checks once, now that the PR is not a draft.

        Checks still running are left to the regular poll, which registered
        them above, and so is everything while the lookup does not yet say
        READY. A check the poll never ingested goes in under its own key; only
        one whose key a webhook spent while the PR was a draft is re-checked
        under the readiness-scoped key. A rate-limited fetch is logged and not
        retried: the regular poll still has the SHA.
        """
        if "/" not in pending.repository:
            logger.warning("Invalid repository format (no '/'): %s", pending.repository)
            return
        if not await self._is_ready(pending):
            return
        owner, repo = pending.repository.split("/", 1)
        result = await self._checks_api.fetch_check_runs(
            owner=owner,
            repo=repo,
            ref=pending.sha,
            installation_id=pending.installation_id,
        )
        if result.rate_limited:
            logger.warning(
                "Rate limited re-checking %s@%s after ready_for_review; held checks not re-checked",
                pending.repository,
                pending.sha[:8],
            )
            return
        for raw_check_run in result.check_runs:
            event = synthesize_check_run_event(raw_check_run, pending)
            if event is None:
                continue
            if await self._ingest_checks_api_event(event, pending) == "deduplicated":
                await self._ingest_checks_api_event(rescope_after_ready_for_review(event), pending)

    async def _is_ready(self, pending: PendingSHA) -> bool:
        """Whether ``pending``'s PR reads READY; DRAFT or UNKNOWN is logged and held (#2058)."""
        reading = await self._draft_state.read_draft_state(
            pending.repository, pending.pr_number, pending.installation_id
        )
        if reading.readiness is PullRequestReadiness.READY:
            return True
        logger.info(
            "Holding completed checks of %s@%s: PR #%d is %s%s; kept pending",
            pending.repository,
            pending.sha[:8],
            pending.pr_number,
            reading.readiness.value,
            f" ({reading.detail})" if reading.detail else "",
        )
        return False

    async def _poll_loop(self) -> None:
        """Main polling loop -- runs until cancelled."""
        while True:
            self._state.update_mode(webhook_stale=self._health.is_stale)
            interval = self._state.current_interval
            self._last_rate_limit_wait = 0.0

            await self._run_iteration()

            sleep_for = max(interval, self._last_rate_limit_wait)
            await self._sleep(sleep_for)

    async def _run_iteration(self) -> None:
        """Run one poll iteration; catches and logs non-cancellation errors."""
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

        # A completed check is not ingested while its PR is a draft or its
        # draft state is unknown: ingesting would spend its dedup key on a
        # held evaluation, and a poll-only install never sees ready_for_review
        # to re-check it. The SHA stays pending until the lookup says READY.
        completed = [c for c in result.check_runs if c.get("status") == "completed"]
        if completed and not await self._is_ready(pending):
            return

        all_completed = len(completed) == len(result.check_runs)
        for raw_check_run in completed:
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
        await self._ingest_checks_api_event(event, pending)

    async def _ingest_checks_api_event(
        self, event: NormalizedEvent, pending: PendingSHA
    ) -> str | None:
        """Feed a synthesized check_run event through the pipeline, logging failures.

        Returns the pipeline status, or None when ingestion raised.
        """
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
            return None
        return result.status

    async def _cleanup_stale_shas(self) -> None:
        """Remove SHAs that have exceeded the TTL (e.g., abandoned PRs)."""
        max_age = timedelta(seconds=self._settings.check_run_sha_ttl_seconds)
        removed = await self._sha_store.cleanup_stale(max_age)
        if removed:
            logger.info("Cleaned up %d stale pending SHA(s)", removed)
