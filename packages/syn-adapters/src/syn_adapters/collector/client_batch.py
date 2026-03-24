"""Collector client batch retry logic.

Extracted from client_transport.py to reduce module complexity.
Handles batch send with exponential backoff retry.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

import httpx

from syn_adapters.collector.client_transport import attempt_send

if TYPE_CHECKING:
    from syn_adapters.collector.client import CollectorClient
    from syn_adapters.collector.models import BatchResponse, EventBatch

logger = logging.getLogger(__name__)


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

    for attempt_num in range(client.max_retries + 1):
        try:
            return await attempt_send(client, batch, headers)
        except httpx.HTTPStatusError as e:
            last_error = e
            if e.response.status_code < 500:
                logger.error("Client error sending batch: %s", e)
                raise
            logger.warning("Server error sending batch (attempt %d): %s", attempt_num + 1, e)
        except httpx.RequestError as e:
            last_error = e
            logger.warning("Request error sending batch (attempt %d): %s", attempt_num + 1, e)

        if attempt_num < client.max_retries:
            client._stats["retries"] += 1
            await asyncio.sleep((2**attempt_num) * 0.1)

    client._stats["events_failed"] += len(batch.events)
    logger.error(
        "Failed to send batch %s after %d attempts", batch.batch_id, client.max_retries + 1
    )
    if last_error:
        raise last_error
    raise RuntimeError("Failed to send batch")
