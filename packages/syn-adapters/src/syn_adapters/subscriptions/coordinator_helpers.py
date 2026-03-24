"""Lifecycle helpers for CoordinatorSubscriptionService.

Extracted from coordinator_service.py to reduce module complexity.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import TYPE_CHECKING

from agentic_logging import get_logger

if TYPE_CHECKING:
    from syn_adapters.subscriptions.coordinator_service import CoordinatorSubscriptionService

logger = get_logger(__name__)


async def run_coordinator(svc: CoordinatorSubscriptionService) -> None:
    """Run the coordinator with exponential-backoff reconnect on error.

    The gRPC subscription can die on startup (event store not ready) or
    mid-run (GOAWAY / RST_STREAM). Rather than letting the task crash and
    leaving projections stale forever, we reset coordinator state and retry
    with backoff (1 s → 2 s → 4 s … capped at 60 s).
    """
    assert svc._coordinator is not None, "Coordinator not initialized"
    delay = 1.0
    max_delay = 60.0

    while svc._running:
        try:
            await svc._coordinator.start()
            delay = 1.0  # reset backoff on clean exit
        except asyncio.CancelledError:
            logger.info("Coordinator subscription cancelled")
            raise
        except Exception as e:
            if not svc._running:
                break
            logger.error(
                "Coordinator subscription error — retrying in %.0fs",
                delay,
                extra={"error": str(e)},
                exc_info=True,
            )
            # coordinator.start() sets _running=True early; reset via stop()
            # so the next call to start() doesn't return "already running".
            await svc._coordinator.stop()
            await asyncio.sleep(delay)
            delay = min(delay * 2, max_delay)


async def stop_coordinator_service(svc: CoordinatorSubscriptionService) -> None:
    """Stop the coordinator subscription service gracefully."""
    if not svc._running:
        return

    logger.info("Stopping coordinator subscription service...")
    svc._running = False

    if svc._coordinator:
        await svc._coordinator.stop()

    if svc._subscription_task:
        svc._subscription_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await svc._subscription_task

    # Close database pool
    if svc._db_pool:
        await svc._db_pool.close()
        logger.info("Checkpoint database pool closed")

    logger.info("Coordinator subscription service stopped")
