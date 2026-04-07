"""Event dispatch logic for EventSubscriptionService.

Extracted from service_live.py to reduce module complexity.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentic_logging import get_logger

if TYPE_CHECKING:
    from event_sourcing import DomainEvent, EventEnvelope

    from syn_adapters.subscriptions.service import EventSubscriptionService

logger = get_logger(__name__)


async def dispatch_event(
    svc: EventSubscriptionService, envelope: EventEnvelope[DomainEvent]
) -> bool:
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
