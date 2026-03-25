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


async def _try_send_attempt(
    client: CollectorClient,
    batch: EventBatch,
    headers: dict[str, str],
    attempt_num: int,
) -> BatchResponse:
    """Attempt a single send, raising on non-retryable or re-raising on retryable errors.

    Returns the BatchResponse on success.
    Raises _RetryableError for server/request errors that should be retried.
    Raises httpx.HTTPStatusError directly for client errors (< 500).
    """
    try:
        return await attempt_send(client, batch, headers)
    except httpx.HTTPStatusError as e:
        if e.response.status_code < 500:
            logger.error("Client error sending batch: %s", e)
            raise
        logger.warning("Server error sending batch (attempt %d): %s", attempt_num + 1, e)
        raise
    except httpx.RequestError as e:
        logger.warning("Request error sending batch (attempt %d): %s", attempt_num + 1, e)
        raise


async def _ensure_client(client: CollectorClient) -> None:
    """Ensure the HTTP client is started."""
    if client._client is None:
        await client.start()
        assert client._client is not None


def _raise_after_exhausted(client: CollectorClient, batch: EventBatch, last_error: Exception | None) -> None:
    """Record failure stats and raise after all retries are exhausted."""
    client._stats["events_failed"] += len(batch.events)
    logger.error(
        "Failed to send batch %s after %d attempts", batch.batch_id, client.max_retries + 1
    )
    if last_error:
        raise last_error
    raise RuntimeError("Failed to send batch")


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
    await _ensure_client(client)
    headers = client._build_auth_headers()
    last_error: Exception | None = None

    for attempt_num in range(client.max_retries + 1):
        try:
            return await _try_send_attempt(client, batch, headers, attempt_num)
        except (httpx.HTTPStatusError, httpx.RequestError) as e:
            last_error = e

        if attempt_num < client.max_retries:
            client._stats["retries"] += 1
            await asyncio.sleep((2**attempt_num) * 0.1)

    _raise_after_exhausted(client, batch, last_error)
