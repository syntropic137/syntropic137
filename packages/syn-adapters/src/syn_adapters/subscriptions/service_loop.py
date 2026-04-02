"""Main subscription loop extracted from service_live.py to reduce module complexity."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from agentic_logging import get_logger

if TYPE_CHECKING:
    from syn_adapters.subscriptions.service import EventSubscriptionService

logger = get_logger(__name__)


async def _run_cycle(svc: EventSubscriptionService) -> None:
    """Run a single catch-up-then-live cycle."""
    await svc._run_catchup()
    svc._caught_up = True
    svc._caught_up_event.set()

    logger.info(
        "[SUBSCRIPTION] Catch-up complete, starting live",
        extra={"position": svc._last_position},
    )
    await svc._run_live_subscription()

    # Live subscription exited — reconnect
    svc._caught_up = False
    svc._caught_up_event.clear()
    logger.warning("[SUBSCRIPTION] Live stream ended, will reconnect")


def _maybe_log_reconnect(svc: EventSubscriptionService, consecutive_failures: int) -> None:
    """Log a reconnect attempt if this is a retry."""
    if consecutive_failures > 0 or svc._reconnect_count > 0:
        svc._reconnect_count += 1
        logger.info("[SUBSCRIPTION] Reconnecting", extra={"attempt": svc._reconnect_count})


async def _handle_loop_error(
    svc: EventSubscriptionService,
    error: Exception,
    retry_delay: float,
    max_retry_delay: float,
) -> float:
    """Log the error, mark not caught up, sleep with backoff. Returns new delay."""
    svc._caught_up = False
    svc._caught_up_event.clear()
    logger.error(
        "[SUBSCRIPTION] Loop failed",
        extra={"error": str(error), "retry_delay": retry_delay},
        exc_info=True,
    )
    if not svc._stop_event.is_set():
        await asyncio.sleep(retry_delay)
    return min(retry_delay * 2, max_retry_delay)


async def subscription_loop(svc: EventSubscriptionService) -> None:
    """Main subscription loop with automatic reconnection.

    Runs catch-up first, then switches to live subscription.
    Retries with exponential backoff on failure.
    """
    retry_delay = 1.0
    max_retry_delay = 60.0
    consecutive_failures = 0

    logger.info("[SUBSCRIPTION] Main loop started", extra={"position": svc._last_position})

    while not svc._stop_event.is_set():
        try:
            _maybe_log_reconnect(svc, consecutive_failures)
            await _run_cycle(svc)
            consecutive_failures = 0
            retry_delay = 1.0
        except asyncio.CancelledError:
            raise
        except Exception as e:
            consecutive_failures += 1
            retry_delay = await _handle_loop_error(svc, e, retry_delay, max_retry_delay)

    logger.info(
        "[SUBSCRIPTION] Main loop stopped",
        extra={"position": svc._last_position, "events": svc._events_processed},
    )
    svc._running = False
