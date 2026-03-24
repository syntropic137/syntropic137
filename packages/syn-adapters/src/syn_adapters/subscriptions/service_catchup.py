"""Catch-up subscription logic for EventSubscriptionService.

Extracted from service.py to reduce module complexity.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentic_logging import get_logger

from syn_adapters.subscriptions.service_catchup_batch import process_catchup_batch

if TYPE_CHECKING:
    from syn_adapters.subscriptions.service import EventSubscriptionService

logger = get_logger(__name__)

# Re-export for backward compatibility
__all__ = ["process_catchup_batch", "run_catchup"]


async def run_catchup(svc: EventSubscriptionService) -> None:
    """Run catch-up subscription to process historical events.

    Uses read_all RPC for reliable batch reading with explicit
    pagination and end-of-batch signals.
    """
    events_in_batch = 0
    from_position = svc._last_position + 1 if svc._last_position > 0 else 0

    logger.info("[SUBSCRIPTION] Catch-up starting", extra={"from": from_position})

    while not svc._stop_event.is_set():
        events, is_end, next_position = await svc._event_store.read_all(
            from_global_nonce=from_position,
            max_count=svc._batch_size,
            forward=True,
        )

        if not events:
            break

        events_in_batch = await process_catchup_batch(svc, events, events_in_batch)

        if events_in_batch >= svc._batch_size:
            await svc._save_position()
            events_in_batch = 0

        if is_end:
            break
        from_position = next_position

    if events_in_batch > 0:
        await svc._save_position()
