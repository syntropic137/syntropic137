"""Collector client batch transport helpers.

Extracted from client_events.py to reduce module complexity.
Handles low-level batch sending and retry logic.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

import httpx

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


async def send_batch(client: CollectorClient, batch: EventBatch) -> BatchResponse:
    """Send a batch with retries.

    Args:
        client: CollectorClient instance.
        batch: EventBatch to send

    Returns:
        BatchResponse from Collector

    Raises:
        httpx.HTTPError: After all retries exhausted
    """
    if client._client is None:
        await client.start()
        assert client._client is not None

    headers = client._build_auth_headers()
    last_error: Exception | None = None

    for attempt in range(client.max_retries + 1):
        try:
            return await attempt_send(client, batch, headers)
        except httpx.HTTPStatusError as e:
            last_error = e
            if e.response.status_code < 500:
                logger.error("Client error sending batch: %s", e)
                raise
            logger.warning("Server error sending batch (attempt %d): %s", attempt + 1, e)
        except httpx.RequestError as e:
            last_error = e
            logger.warning("Request error sending batch (attempt %d): %s", attempt + 1, e)

        if attempt < client.max_retries:
            client._stats["retries"] += 1
            await asyncio.sleep((2**attempt) * 0.1)

    client._stats["events_failed"] += len(batch.events)
    logger.error(
        "Failed to send batch %s after %d attempts", batch.batch_id, client.max_retries + 1
    )
    if last_error:
        raise last_error
    raise RuntimeError("Failed to send batch")
