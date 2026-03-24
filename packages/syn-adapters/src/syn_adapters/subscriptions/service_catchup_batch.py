"""Catch-up batch processing for EventSubscriptionService.

Extracted from service_catchup.py to reduce module complexity.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from agentic_logging import get_logger

if TYPE_CHECKING:
    from collections.abc import Sequence

    from syn_adapters.subscriptions.service import EventSubscriptionService

logger = get_logger(__name__)


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
