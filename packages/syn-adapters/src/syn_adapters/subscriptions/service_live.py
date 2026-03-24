"""Live subscription logic for EventSubscriptionService.

Extracted from service.py to reduce module complexity.
subscription_loop has been moved to service_loop.py.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from agentic_logging import get_logger

from syn_adapters.subscriptions.service_loop import subscription_loop

if TYPE_CHECKING:
    from syn_adapters.subscriptions.service import EventSubscriptionService

logger = get_logger(__name__)

__all__ = ["subscription_loop", "dispatch_event", "run_live_subscription"]


async def dispatch_event(svc: EventSubscriptionService, envelope: object) -> bool:
    """Dispatch an event to projections via validated envelope.

    This uses process_event_envelope() which validates that events
    came through the proper event store channel, enforcing event
    sourcing guarantees.

    Args:
        svc: The subscription service instance.
        envelope: Event envelope from the event store.

    Returns:
        True if event was successfully dispatched, False if it failed.
        Position should only be advanced if this returns True.
    """
    event_type = getattr(getattr(envelope, "event", None), "event_type", "unknown")
    global_nonce = getattr(getattr(envelope, "metadata", None), "global_nonce", None)

    try:
        # Use the new validated dispatch method
        # This validates provenance and extracts event data
        provenance = await svc._projection_manager.process_event_envelope(envelope)
        svc._events_processed += 1

        logger.debug(
            "[SUBSCRIPTION] ✅ Event dispatched to projections",
            extra={
                "event_type": provenance.event_type,
                "stream_id": provenance.stream_id,
                "global_nonce": provenance.global_nonce,
                "total_events_processed": svc._events_processed,
            },
        )
        return True

    except ValueError as e:
        # Invalid envelope - log but DON'T advance position
        # This event needs to be investigated, not skipped
        logger.error(
            "[SUBSCRIPTION] ❌ Invalid event envelope - NOT advancing position",
            extra={
                "error": str(e),
                "event_type": event_type,
                "global_nonce": global_nonce,
            },
        )
        return False

    except Exception as e:
        # Dispatch failed - DON'T advance position
        # Event will be retried on next restart
        logger.error(
            "[SUBSCRIPTION] ❌ Failed to dispatch event - NOT advancing position",
            extra={
                "error": str(e),
                "error_type": type(e).__name__,
                "event_type": event_type,
                "global_nonce": global_nonce,
            },
            exc_info=True,
        )
        return False


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
        if events_since_save >= svc._batch_size or (now - last_save_time).total_seconds() >= svc._position_save_interval:
            await svc._save_position()
            events_since_save = 0
            last_save_time = now
