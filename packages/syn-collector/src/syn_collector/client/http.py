"""HTTP client for sending events to collector service.

Provides batched event sending with retry logic
and configurable intervals.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime

import httpx

from syn_collector.events.types import BatchResponse, CollectedEvent, EventBatch

logger = logging.getLogger(__name__)


class EventCollectorClient:
    """HTTP client for sending events to collector.

    Buffers events and sends in batches to reduce network
    overhead. Supports automatic retries with exponential backoff.

    Attributes:
        collector_url: Base URL of collector service
        batch_size: Events per batch
        batch_interval_ms: Max ms between flushes
    """

    def __init__(
        self,
        collector_url: str,
        *,
        api_key: str | None = None,
        agent_id: str | None = None,
        batch_size: int = 100,
        batch_interval_ms: int = 1000,
        max_retries: int = 3,
        timeout_seconds: float = 30.0,
    ) -> None:
        """Initialize the HTTP client.

        Args:
            collector_url: Base URL of collector service
            api_key: Optional API key for authentication
            agent_id: Identifier for this agent/sidecar
            batch_size: Number of events per batch
            batch_interval_ms: Max milliseconds between flushes
            max_retries: Maximum retry attempts
            timeout_seconds: HTTP request timeout
        """
        self.collector_url = collector_url.rstrip("/")
        self.api_key = api_key
        self.agent_id = agent_id or self._generate_agent_id()
        self.batch_size = batch_size
        self.batch_interval_ms = batch_interval_ms
        self.max_retries = max_retries
        self.timeout_seconds = timeout_seconds

        self._buffer: list[CollectedEvent] = []
        self._client: httpx.AsyncClient | None = None
        self._lock = asyncio.Lock()

        # Statistics
        self._stats = {
            "events_sent": 0,
            "events_failed": 0,
            "batches_sent": 0,
            "retries": 0,
        }

    async def __aenter__(self) -> EventCollectorClient:
        """Async context manager entry."""
        await self.start()
        return self

    async def __aexit__(self, *args: object) -> None:
        """Async context manager exit - flush remaining events."""
        await self.close()

    async def start(self) -> None:
        """Start the HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout_seconds),
            )

    async def close(self) -> None:
        """Close client and flush remaining events."""
        await self.flush()
        if self._client:
            await self._client.aclose()
            self._client = None

    async def emit(self, event: CollectedEvent) -> None:
        """Add event to buffer, flush if batch is full.

        Args:
            event: Event to send
        """
        async with self._lock:
            self._buffer.append(event)

        if len(self._buffer) >= self.batch_size:
            await self.flush()

    async def flush(self) -> BatchResponse | None:
        """Send buffered events to collector.

        Returns:
            BatchResponse from collector, or None if buffer empty
        """
        async with self._lock:
            if not self._buffer:
                return None

            events = self._buffer.copy()
            self._buffer.clear()

        batch = EventBatch(
            agent_id=self.agent_id,
            batch_id=self._generate_batch_id(),
            events=events,
        )

        return await self._send_batch(batch)

    async def _send_batch(self, batch: EventBatch) -> BatchResponse:
        """Send a batch with retries.

        Args:
            batch: EventBatch to send

        Returns:
            BatchResponse from collector

        Raises:
            httpx.HTTPError: After all retries exhausted
        """
        if self._client is None:
            await self.start()
            assert self._client is not None

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        last_error: Exception | None = None

        for attempt in range(self.max_retries + 1):
            try:
                response = await self._client.post(
                    f"{self.collector_url}/events",
                    json=batch.model_dump(mode="json"),
                    headers=headers,
                )
                response.raise_for_status()

                result = BatchResponse(**response.json())

                # Update stats
                self._stats["events_sent"] += result.accepted
                self._stats["batches_sent"] += 1

                logger.debug(
                    f"Batch {batch.batch_id} sent: {result.accepted} accepted, {result.duplicates} duplicates",
                )

                return result

            except httpx.HTTPStatusError as e:
                last_error = e
                if e.response.status_code < 500:
                    # Client error, don't retry
                    logger.error(f"Client error sending batch: {e}")
                    raise

                logger.warning(f"Server error sending batch (attempt {attempt + 1}): {e}")

            except httpx.RequestError as e:
                last_error = e
                logger.warning(f"Request error sending batch (attempt {attempt + 1}): {e}")

            # Exponential backoff
            if attempt < self.max_retries:
                self._stats["retries"] += 1
                delay = (2**attempt) * 0.1  # 0.1s, 0.2s, 0.4s, ...
                await asyncio.sleep(delay)

        # All retries exhausted
        self._stats["events_failed"] += len(batch.events)
        logger.error(f"Failed to send batch {batch.batch_id} after {self.max_retries + 1} attempts")

        if last_error:
            raise last_error
        raise RuntimeError("Failed to send batch")

    def _generate_agent_id(self) -> str:
        """Generate a unique agent ID.

        Returns:
            Agent identifier string
        """
        return f"agent-{uuid.uuid4().hex[:8]}"

    def _generate_batch_id(self) -> str:
        """Generate a unique batch ID.

        Returns:
            Batch identifier string
        """
        timestamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
        unique = uuid.uuid4().hex[:6]
        return f"batch-{timestamp}-{unique}"

    @property
    def buffer_size(self) -> int:
        """Current number of buffered events."""
        return len(self._buffer)

    @property
    def stats(self) -> dict[str, int]:
        """Get client statistics.

        Returns:
            Dict with events_sent, events_failed, batches_sent, retries
        """
        return {
            **self._stats,
            "buffer_size": len(self._buffer),
        }
