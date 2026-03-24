"""Live subscription logic for EventSubscriptionService.

Extracted from service.py to reduce module complexity.
subscription_loop has been moved to service_loop.py.
dispatch_event has been moved to service_dispatch.py.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from agentic_logging import get_logger

from syn_adapters.subscriptions.service_dispatch import dispatch_event as dispatch_event
from syn_adapters.subscriptions.service_loop import subscription_loop

if TYPE_CHECKING:
    from syn_adapters.subscriptions.service import EventSubscriptionService

logger = get_logger(__name__)

__all__ = ["dispatch_event", "run_live_subscription", "subscription_loop"]


async def run_live_subscription(svc: EventSubscriptionService) -> None:
    """Run live subscription for real-time events.

    Exits (not raises) when the stream ends, allowing the main loop to reconnect.
    """
    events_since_save = 0
    last_save_time = datetime.now(UTC)
    start_position = svc._last_position + 1

    logger.info("[SUBSCRIPTION] Live subscription connecting", extra={"from": start_position})

    async for envelope in svc._event_store.subscribe(from_global_nonce=start_position):
        if svc._stop_event.is_set():
            return

        svc._last_event_time = datetime.now(UTC)
        dispatch_success = await svc._dispatch_event(envelope)

        # CRITICAL: Only advance position if dispatch succeeded
        if dispatch_success:
            events_since_save += 1
            if envelope.metadata.global_nonce is not None:
                svc._last_position = envelope.metadata.global_nonce
        else:
            nonce = getattr(getattr(envelope, "metadata", None), "global_nonce", None)
            raise RuntimeError(f"Event dispatch failed at position {nonce}. Triggering reconnect.")

        # Save position periodically
        now = datetime.now(UTC)
        if (
            events_since_save >= svc._batch_size
            or (now - last_save_time).total_seconds() >= svc._position_save_interval
        ):
            await svc._save_position()
            events_since_save = 0
            last_save_time = now
