"""Stop/status helpers for EventSubscriptionService.

Extracted from service.py to reduce module complexity.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import TYPE_CHECKING

from agentic_logging import get_logger

if TYPE_CHECKING:
    from syn_adapters.subscriptions.service import EventSubscriptionService

logger = get_logger(__name__)


def get_status(svc: EventSubscriptionService) -> dict:
    """Get detailed status of the subscription service.

    Returns a dictionary with current state information useful for
    debugging and health checks.
    """
    status = {
        "running": svc._running,
        "caught_up": svc._caught_up,
        "last_position": svc._last_position,
        "events_processed": svc._events_processed,
        "reconnect_count": svc._reconnect_count,
        "last_event_time": svc._last_event_time.isoformat() if svc._last_event_time else None,
        "last_position_save": svc._last_position_save.isoformat()
        if svc._last_position_save
        else None,
    }
    logger.debug(
        "[SUBSCRIPTION] Status requested",
        extra=status,
    )
    return status


async def stop_service(svc: EventSubscriptionService) -> None:
    """Stop the subscription service gracefully.

    This signals the subscription to stop, waits for cleanup,
    and saves the final position.
    """
    if not svc._running:
        logger.warning("Subscription service not running")
        return

    logger.info("Stopping event subscription service...")

    # Signal stop
    svc._stop_event.set()
    svc._running = False

    # Wait for task to complete
    if svc._subscription_task:
        try:
            await asyncio.wait_for(svc._subscription_task, timeout=5.0)
        except TimeoutError:
            logger.warning("Subscription task did not stop in time, cancelling")
            svc._subscription_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await svc._subscription_task

    # Save final position
    await svc._save_position()

    logger.info(
        "Event subscription service stopped",
        extra={
            "last_position": svc._last_position,
            "events_processed": svc._events_processed,
        },
    )
