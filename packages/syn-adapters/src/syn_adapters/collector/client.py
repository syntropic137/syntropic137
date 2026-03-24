"""HTTP client for sending observability events to Collector service.

This client is used by the Executor to send tool execution events
to the Collector as observation events (Pattern 2: Event Log + CQRS).

See: ADR-017, ADR-018, PROJECT-PLAN_20251209_observability-unification.md
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

import httpx

from syn_adapters.collector.client_batch import send_batch as _send_batch_fn
from syn_adapters.collector.client_events import send_observation as _send_observation_fn
from syn_adapters.collector.client_events import send_tool_blocked as _send_tool_blocked_fn
from syn_adapters.collector.client_events import send_tool_completed as _send_tool_completed_fn
from syn_adapters.collector.client_events import send_tool_started as _send_tool_started_fn
from syn_adapters.collector.client_transport import attempt_send as _attempt_send_fn
from syn_adapters.collector.models import (
    BatchResponse,
    CollectorEvent,
    EventBatch,
    generate_event_id,
    generate_tool_event_id,
)

# Re-export for backward compatibility
__all__ = [
    "BatchResponse",
    "CollectorClient",
    "CollectorEvent",
    "EventBatch",
    "generate_event_id",
    "generate_tool_event_id",
]

logger = logging.getLogger(__name__)


class CollectorClient:
    """HTTP client for sending observation events to Collector service.

    This client is used by the Executor to send tool execution events.
    Events are buffered and sent in batches to reduce network overhead.

    Example:
        async with CollectorClient("http://localhost:8080") as client:
            await client.send_tool_started(
                session_id="session-123",
                tool_name="Read",
                tool_use_id="toolu_abc",
                tool_input={"file_path": "/src/main.py"},
            )

    Attributes:
        collector_url: Base URL of Collector service
        batch_size: Events per batch (default: 100)
        max_retries: Maximum retry attempts (default: 3)
    """

    def __init__(
        self,
        collector_url: str,
        *,
        api_key: str | None = None,
        agent_id: str | None = None,
        batch_size: int = 100,
        max_retries: int = 3,
        timeout_seconds: float = 30.0,
    ) -> None:
        """Initialize the Collector client.

        Args:
            collector_url: Base URL of Collector service
            api_key: Optional API key for authentication
            agent_id: Identifier for this agent
            batch_size: Number of events per batch
            max_retries: Maximum retry attempts
            timeout_seconds: HTTP request timeout
        """
        self.collector_url = collector_url.rstrip("/")
        self.api_key = api_key
        self.agent_id = agent_id or f"executor-{uuid.uuid4().hex[:8]}"
        self.batch_size = batch_size
        self.max_retries = max_retries
        self.timeout_seconds = timeout_seconds

        self._buffer: list[CollectorEvent] = []
        self._client: httpx.AsyncClient | None = None
        self._lock = asyncio.Lock()

        # Statistics
        self._stats = {
            "events_sent": 0,
            "events_failed": 0,
            "batches_sent": 0,
            "retries": 0,
        }

    async def __aenter__(self) -> CollectorClient:
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

    async def emit(self, event: CollectorEvent) -> None:
        """Add event to buffer, flush if batch is full.

        Args:
            event: Event to send
        """
        async with self._lock:
            self._buffer.append(event)

        if len(self._buffer) >= self.batch_size:
            await self.flush()

    async def flush(self) -> BatchResponse | None:
        """Send buffered events to Collector.

        Returns:
            BatchResponse from Collector, or None if buffer empty
        """
        async with self._lock:
            if not self._buffer:
                return None

            events = self._buffer.copy()
            self._buffer.clear()

        batch = EventBatch(
            agent_id=self.agent_id,
            batch_id=f"batch-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}",
            events=events,
        )

        return await self._send_batch(batch)

    async def _attempt_send(
        self, batch: EventBatch, headers: dict[str, str]
    ) -> BatchResponse:
        """Attempt a single batch send. See client_transport.attempt_send for details."""
        return await _attempt_send_fn(self, batch, headers)

    async def _send_batch(self, batch: EventBatch) -> BatchResponse:
        """Send a batch with retries. See client_transport.send_batch for details."""
        return await _send_batch_fn(self, batch)

    def _build_auth_headers(self) -> dict[str, str]:
        """Build HTTP headers with optional auth."""
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    # Convenience methods for tool events

    async def send_tool_started(
        self,
        session_id: str,
        tool_name: str,
        tool_use_id: str,
        tool_input: dict[str, Any],
        *,
        timestamp: datetime | None = None,
    ) -> None:
        """Send a tool_execution_started event. See client_events.send_tool_started."""
        await _send_tool_started_fn(
            self, session_id, tool_name, tool_use_id, tool_input, timestamp=timestamp
        )

    async def send_tool_completed(
        self,
        session_id: str,
        tool_name: str,
        tool_use_id: str,
        duration_ms: int,
        success: bool,
        *,
        error_message: str | None = None,
        timestamp: datetime | None = None,
    ) -> None:
        """Send a tool_execution_completed event. See client_events.send_tool_completed."""
        await _send_tool_completed_fn(
            self,
            session_id,
            tool_name,
            tool_use_id,
            duration_ms,
            success,
            error_message=error_message,
            timestamp=timestamp,
        )

    async def send_tool_blocked(
        self,
        session_id: str,
        tool_name: str,
        tool_use_id: str,
        reason: str,
        *,
        validator_name: str | None = None,
        timestamp: datetime | None = None,
    ) -> None:
        """Send a tool_blocked event. See client_events.send_tool_blocked."""
        await _send_tool_blocked_fn(
            self, session_id, tool_name, tool_use_id, reason, validator_name=validator_name, timestamp=timestamp
        )

    async def send_observation(self, event: dict[str, Any]) -> None:
        """Send a generic observation event. See client_events.send_observation."""
        await _send_observation_fn(self, event)

    @property
    def buffer_size(self) -> int:
        """Current number of buffered events."""
        return len(self._buffer)

    @property
    def stats(self) -> dict[str, int]:
        """Get client statistics."""
        return {
            **self._stats,
            "buffer_size": len(self._buffer),
        }
