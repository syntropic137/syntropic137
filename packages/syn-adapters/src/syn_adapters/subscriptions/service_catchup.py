"""Catch-up subscription logic for EventSubscriptionService.

Extracted from service.py to reduce module complexity.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from agentic_logging import get_logger

if TYPE_CHECKING:
    from syn_adapters.subscriptions.service import EventSubscriptionService

logger = get_logger(__name__)


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


async def process_catchup_batch(
    svc: EventSubscriptionService,
    events: Sequence[object],
    events_in_batch: int,
) -> int:
    """Process a batch of catch-up events, advancing position on success.

    Returns updated events_in_batch count.
    Raises RuntimeError if dispatch fails (triggers reconnect).
    """
    for envelope in events:
        if svc._stop_event.is_set():
            break

        dispatch_success = await svc._dispatch_event(envelope)
        svc._last_event_time = datetime.now(UTC)

        # CRITICAL: Only advance position if dispatch succeeded
        if dispatch_success:
            events_in_batch += 1
            if envelope.metadata.global_nonce is not None:  # type: ignore[union-attr]
                svc._last_position = envelope.metadata.global_nonce  # type: ignore[union-attr]
        else:
            nonce = getattr(getattr(envelope, "metadata", None), "global_nonce", None)
            raise RuntimeError(
                f"Event dispatch failed at position {nonce}. "
                "Stopping to prevent position drift. Will retry on reconnect."
            )

    return events_in_batch
