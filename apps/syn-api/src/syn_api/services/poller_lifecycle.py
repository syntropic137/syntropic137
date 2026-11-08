"""Start, stop and describe the GitHub pollers (ADR-050, ADR-060).

Kept out of lifecycle.py the way feedback_lifecycle.py is: lifecycle owns the
startup sequence and its registry, this module owns what the Events API and
Checks API pollers need from it.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Protocol

from syn_api.types import EventPollerHealth

if TYPE_CHECKING:
    from syn_domain.contexts.github.services import (
        CheckRunIngestionService,
        GitHubEventIngestionScheduler,
    )

logger = logging.getLogger(__name__)


class PollerState(Protocol):
    """The part of ``LifecycleState`` that holds the running pollers."""

    event_poller: GitHubEventIngestionScheduler | None
    check_run_poller: CheckRunIngestionService | None


def describe_event_poller(poller: GitHubEventIngestionScheduler | None) -> EventPollerHealth | None:
    """The event poller's health block, or None when it is not running."""
    if poller is None or not poller.is_running:
        return None
    return EventPollerHealth(unresolved_triggers=poller.unresolved_triggers)


async def init_event_poller(state: PollerState) -> None:
    """Start the GitHub Events API poller.

    See ADR-060: Restart-safe trigger deduplication (cold-start fence, cursor persistence).
    """
    from syn_shared.settings import get_settings

    settings = get_settings()

    if not settings.github.is_configured:
        logger.info("GitHub App not configured — event poller disabled")
        return

    if not settings.polling.enabled:
        logger.info("Event polling disabled by configuration")
        return

    from syn_adapters.github.client import get_github_client
    from syn_adapters.github.events_api_client import GitHubEventsAPIClient
    from syn_api._wiring import (
        get_event_pipeline,
        get_trigger_store,
        get_webhook_health_tracker,
    )
    from syn_domain.contexts.github.services import (
        GitHubEventIngestionScheduler,
        GitHubRepoIngestionService,
    )

    # ADR-060: Wire persistent cursor store for restart-safe polling.
    # HistoricalPoller base class uses this for cold-start fence + ETag persistence.
    cursor_store = None
    try:
        from syn_api._wiring_db import get_shared_db_pool

        pool = get_shared_db_pool()
        if pool is not None:
            from syn_adapters.github.poller_cursor_store import PostgresPollerCursorStore

            cursor_store = PostgresPollerCursorStore(pool)  # type: ignore[arg-type]  # asyncpg.Pool vs AsyncConnectionPool
            logger.info("Poller cursor store initialized (ADR-060)")
    except Exception:
        logger.warning("Cursor store unavailable - poller will re-fetch on restart", exc_info=True)

    if cursor_store is None:
        if not settings.uses_in_memory_stores:
            logger.error(
                "Durable poller cursor store unavailable in production - "
                "disabling event poller to prevent cold-start restart storms (ADR-060)"
            )
            return
        from syn_adapters.github.poller_cursor_store import InMemoryPollerCursorStore

        cursor_store = InMemoryPollerCursorStore()
        logger.warning("Using in-memory cursor store - cold-start fence resets on restart")

    from syn_adapters.repo_names import OrganizationRepoNames

    events_client = GitHubEventsAPIClient(get_github_client())
    repo_service = GitHubRepoIngestionService(
        events_api=events_client,
        pipeline=get_event_pipeline(),
        cursor_store=cursor_store,
    )
    poller = GitHubEventIngestionScheduler(
        repo_service=repo_service,
        health_tracker=get_webhook_health_tracker(),
        trigger_store=get_trigger_store(),
        repo_names=OrganizationRepoNames(),
        settings=settings.polling,
    )
    await poller.start()
    state.event_poller = poller
    logger.info("GitHub event poller started")


async def shutdown_event_poller(state: PollerState) -> None:
    """Stop the GitHub event poller."""
    if state.event_poller is not None:
        await state.event_poller.stop()
        state.event_poller = None


async def init_check_run_poller(state: PollerState) -> None:
    """Start the check-run poller for poll-based self-healing (#602).

    Polls the GitHub Checks API for CI failures on PR commits. Enables
    self-healing without webhooks — zero-config onboarding.
    """
    from syn_shared.settings import get_settings

    settings = get_settings()

    if not settings.github.is_configured:
        logger.info("GitHub App not configured — check-run poller disabled")
        return

    if not settings.polling.enabled:
        logger.info("Event polling disabled — check-run poller disabled")
        return

    from syn_adapters.github.checks_api_client import GitHubChecksAPIClient
    from syn_adapters.github.client import get_github_client
    from syn_api._wiring import (
        get_event_pipeline,
        get_pending_sha_store,
        get_trigger_store,
        get_webhook_health_tracker,
    )
    from syn_domain.contexts.github.services import CheckRunIngestionService

    poller = CheckRunIngestionService(
        checks_api=GitHubChecksAPIClient(get_github_client()),
        pipeline=get_event_pipeline(),
        sha_store=get_pending_sha_store(),
        health_tracker=get_webhook_health_tracker(),
        trigger_store=get_trigger_store(),
        settings=settings.polling,
    )
    get_event_pipeline().add_observer(poller.on_pr_event)
    await poller.start()
    state.check_run_poller = poller
    logger.info("Check-run poller started")


async def shutdown_check_run_poller(state: PollerState) -> None:
    """Stop the check-run poller."""
    if state.check_run_poller is not None:
        await state.check_run_poller.stop()
        state.check_run_poller = None
