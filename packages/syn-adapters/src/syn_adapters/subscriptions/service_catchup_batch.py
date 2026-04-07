"""Catch-up batch processing for EventSubscriptionService.

Extracted from service_catchup.py to reduce module complexity.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from agentic_logging import get_logger

if TYPE_CHECKING:
    from collections.abc import Sequence

    from event_sourcing import DomainEvent, EventEnvelope

    from syn_adapters.subscriptions.service import EventSubscriptionService

logger = get_logger(__name__)


def _advance_position(svc: EventSubscriptionService, envelope: object) -> None:
    """Advance the service position from the envelope's global nonce."""
    nonce = getattr(getattr(envelope, "metadata", None), "global_nonce", None)
    if nonce is not None:
        svc._last_position = nonce


def _raise_dispatch_failure(envelope: object) -> None:
    """Raise RuntimeError for a failed dispatch to trigger reconnect."""
    nonce = getattr(getattr(envelope, "metadata", None), "global_nonce", None)
    raise RuntimeError(
        f"Event dispatch failed at position {nonce}. "
        "Stopping to prevent position drift. Will retry on reconnect."
    )


async def process_catchup_batch(
    svc: EventSubscriptionService,
    events: Sequence[EventEnvelope[DomainEvent]],
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
            _advance_position(svc, envelope)
        else:
            _raise_dispatch_failure(envelope)

    return events_in_batch
