"""Collector client low-level transport helpers.

Extracted from client_events.py to reduce module complexity.
Handles single batch HTTP send (no retries).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from syn_adapters.collector.models import BatchResponse, EventBatch

if TYPE_CHECKING:
    from syn_adapters.collector.client import CollectorClient

logger = logging.getLogger(__name__)


async def attempt_send(
    client: CollectorClient, batch: EventBatch, headers: dict[str, str]
) -> BatchResponse:
    """Attempt a single batch send (no retries).

    Args:
        client: CollectorClient instance.
        batch: EventBatch to send
        headers: HTTP headers for the request

    Returns:
        BatchResponse on success

    Raises:
        httpx.HTTPStatusError: On client errors (4xx) — not retryable.
        httpx.HTTPStatusError: On server errors (5xx) — retryable.
        httpx.RequestError: On connection/transport errors — retryable.
    """
    assert client._client is not None
    response = await client._client.post(
        f"{client.collector_url}/events",
        json=batch.model_dump(mode="json"),
        headers=headers,
    )
    response.raise_for_status()

    result = BatchResponse(**response.json())

    client._stats["events_sent"] += result.accepted
    client._stats["batches_sent"] += 1

    logger.debug(
        "Batch %s sent: %d accepted, %d duplicates",
        batch.batch_id,
        result.accepted,
        result.duplicates,
    )

    return result
