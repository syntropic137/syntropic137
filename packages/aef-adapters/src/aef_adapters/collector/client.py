"""HTTP client for sending observability events to Collector service.

This client is used by the Executor to send tool execution events
to the Collector as observation events (Pattern 2: Event Log + CQRS).

See: ADR-017, ADR-018, PROJECT-PLAN_20251209_observability-unification.md
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

import httpx
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class CollectorEvent(BaseModel):
    """A single observation event to send to the Collector.

    Attributes:
        event_id: Deterministic ID for deduplication (SHA256 hash)
        event_type: Type of event (e.g., "tool_execution_started")
        session_id: Agent session identifier
        timestamp: When the event occurred (ISO 8601)
        data: Event-specific payload
    """

    event_id: str = Field(..., description="Deterministic ID for deduplication")
    event_type: str = Field(..., description="Type of event")
    session_id: str = Field(..., description="Agent session identifier")
    timestamp: datetime = Field(..., description="When the event occurred")
    data: dict[str, Any] = Field(default_factory=dict, description="Event payload")

    model_config = {"frozen": True}


class EventBatch(BaseModel):
    """Batch of events to send to Collector."""

    agent_id: str = Field(..., description="Agent sending the batch")
    batch_id: str = Field(..., description="Unique batch identifier")
    events: list[CollectorEvent] = Field(default_factory=list, description="Events in batch")


class BatchResponse(BaseModel):
    """Response from Collector after processing a batch."""

    accepted: int = Field(..., ge=0, description="Events successfully accepted")
    duplicates: int = Field(..., ge=0, description="Duplicate events skipped")
    batch_id: str = Field(..., description="Batch ID for correlation")


def generate_event_id(
    session_id: str,
    event_type: str,
    timestamp: datetime,
    content_hash: str | None = None,
) -> str:
    """Generate deterministic event ID for deduplication.

    Same inputs always produce the same event_id.

    Args:
        session_id: Agent session identifier
        event_type: Type of event
        timestamp: When the event occurred
        content_hash: Optional hash of event-specific content

    Returns:
        32-character hex string (truncated SHA256)
    """
    key_parts = [session_id, event_type, timestamp.isoformat()]
    if content_hash:
        key_parts.append(content_hash)
    key = "|".join(key_parts)
    return hashlib.sha256(key.encode()).hexdigest()[:32]


def generate_tool_event_id(
    session_id: str,
    event_type: str,
    timestamp: datetime,
    tool_name: str,
    tool_use_id: str,
) -> str:
    """Generate event ID for tool execution events.

    Args:
        session_id: Agent session identifier
        event_type: Type of tool event (started/completed/blocked)
        timestamp: When the event occurred
        tool_name: Name of the tool
        tool_use_id: Claude's tool use identifier

    Returns:
        32-character hex string
    """
    content = f"{tool_name}|{tool_use_id}"
    content_hash = hashlib.sha256(content.encode()).hexdigest()[:16]
    return generate_event_id(session_id, event_type, timestamp, content_hash)


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

    async def _send_batch(self, batch: EventBatch) -> BatchResponse:
        """Send a batch with retries.

        Args:
            batch: EventBatch to send

        Returns:
            BatchResponse from Collector

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
                    "Batch %s sent: %d accepted, %d duplicates",
                    batch.batch_id,
                    result.accepted,
                    result.duplicates,
                )

                return result

            except httpx.HTTPStatusError as e:
                last_error = e
                if e.response.status_code < 500:
                    logger.error("Client error sending batch: %s", e)
                    raise

                logger.warning("Server error sending batch (attempt %d): %s", attempt + 1, e)

            except httpx.RequestError as e:
                last_error = e
                logger.warning("Request error sending batch (attempt %d): %s", attempt + 1, e)

            # Exponential backoff
            if attempt < self.max_retries:
                self._stats["retries"] += 1
                delay = (2**attempt) * 0.1
                await asyncio.sleep(delay)

        # All retries exhausted
        self._stats["events_failed"] += len(batch.events)
        logger.error(
            "Failed to send batch %s after %d attempts", batch.batch_id, self.max_retries + 1
        )

        if last_error:
            raise last_error
        raise RuntimeError("Failed to send batch")

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
        """Send a tool_execution_started event.

        Args:
            session_id: Agent session identifier
            tool_name: Name of the tool being executed
            tool_use_id: Claude's tool use identifier
            tool_input: Tool input parameters
            timestamp: Optional timestamp (defaults to now)
        """
        ts = timestamp or datetime.now(UTC)
        event = CollectorEvent(
            event_id=generate_tool_event_id(
                session_id, "tool_execution_started", ts, tool_name, tool_use_id
            ),
            event_type="tool_execution_started",
            session_id=session_id,
            timestamp=ts,
            data={
                "tool_name": tool_name,
                "tool_use_id": tool_use_id,
                "tool_input": tool_input,
            },
        )
        await self.emit(event)
        logger.debug(
            "Queued tool_execution_started: session=%s, tool=%s, tool_use_id=%s",
            session_id,
            tool_name,
            tool_use_id,
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
        """Send a tool_execution_completed event.

        Args:
            session_id: Agent session identifier
            tool_name: Name of the tool
            tool_use_id: Claude's tool use identifier
            duration_ms: Execution duration in milliseconds
            success: Whether execution succeeded
            error_message: Optional error message if failed
            timestamp: Optional timestamp (defaults to now)
        """
        ts = timestamp or datetime.now(UTC)
        event = CollectorEvent(
            event_id=generate_tool_event_id(
                session_id, "tool_execution_completed", ts, tool_name, tool_use_id
            ),
            event_type="tool_execution_completed",
            session_id=session_id,
            timestamp=ts,
            data={
                "tool_name": tool_name,
                "tool_use_id": tool_use_id,
                "duration_ms": duration_ms,
                "success": success,
                "error_message": error_message,
            },
        )
        await self.emit(event)
        logger.debug(
            "Queued tool_execution_completed: session=%s, tool=%s, duration=%dms, success=%s",
            session_id,
            tool_name,
            duration_ms,
            success,
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
        """Send a tool_blocked event.

        Args:
            session_id: Agent session identifier
            tool_name: Name of the tool
            tool_use_id: Claude's tool use identifier
            reason: Why the tool was blocked
            validator_name: Name of the validator that blocked it
            timestamp: Optional timestamp (defaults to now)
        """
        ts = timestamp or datetime.now(UTC)
        event = CollectorEvent(
            event_id=generate_tool_event_id(session_id, "tool_blocked", ts, tool_name, tool_use_id),
            event_type="tool_blocked",
            session_id=session_id,
            timestamp=ts,
            data={
                "tool_name": tool_name,
                "tool_use_id": tool_use_id,
                "reason": reason,
                "validator_name": validator_name,
            },
        )
        await self.emit(event)
        logger.debug(
            "Queued tool_blocked: session=%s, tool=%s, reason=%s",
            session_id,
            tool_name,
            reason,
        )

    async def send_observation(self, event: dict[str, Any]) -> None:
        """Send a generic observation event.

        This is for custom events that don't fit the convenience methods.

        Args:
            event: Event dictionary with event_type, session_id, data, etc.
        """
        ts = event.get("timestamp") or datetime.now(UTC)
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts)

        collector_event = CollectorEvent(
            event_id=event.get("event_id")
            or generate_event_id(
                event.get("session_id", "unknown"),
                event.get("event_type", "unknown"),
                ts,
                None,
            ),
            event_type=event.get("event_type", "unknown"),
            session_id=event.get("session_id", "unknown"),
            timestamp=ts,
            data=event.get("data", {}),
        )
        await self.emit(collector_event)

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
