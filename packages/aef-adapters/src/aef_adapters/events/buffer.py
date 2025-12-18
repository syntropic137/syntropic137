"""Event buffer for batch processing.

Buffer events in memory and flush to AgentEventStore in batches
for high-throughput event storage.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from aef_adapters.events.store import AgentEventStore

logger = logging.getLogger(__name__)


class EventBuffer:
    """Buffer events and flush in batches.

    This buffer collects events from multiple agent runners and flushes
    them to the AgentEventStore in batches for optimal database performance.

    Usage:
        store = AgentEventStore(connection_string)
        await store.initialize()

        buffer = EventBuffer(store, flush_size=1000)
        await buffer.start()

        # Add events from agent runners
        await buffer.add({"event_type": "tool_started", ...})
        await buffer.add({"event_type": "tool_completed", ...})

        # Events are automatically flushed when:
        # - Buffer reaches flush_size
        # - flush_interval seconds pass
        # - stop() is called

        await buffer.stop()
    """

    def __init__(
        self,
        store: AgentEventStore,
        flush_size: int = 1000,
        flush_interval: float = 0.1,
    ) -> None:
        """Initialize the event buffer.

        Args:
            store: AgentEventStore to flush events to
            flush_size: Number of events to trigger a flush
            flush_interval: Seconds between periodic flushes
        """
        self._store = store
        self._flush_size = flush_size
        self._flush_interval = flush_interval

        self._buffer: list[dict[str, Any]] = []
        self._lock = asyncio.Lock()
        self._flush_task: asyncio.Task[None] | None = None
        self._running = False

        # Metrics
        self._total_events = 0
        self._total_flushes = 0

    @property
    def size(self) -> int:
        """Current number of events in the buffer."""
        return len(self._buffer)

    @property
    def total_events(self) -> int:
        """Total events processed since start."""
        return self._total_events

    @property
    def total_flushes(self) -> int:
        """Total flush operations since start."""
        return self._total_flushes

    async def add(
        self,
        event: dict[str, Any],
        execution_id: str | None = None,
        phase_id: str | None = None,
    ) -> None:
        """Add an event to the buffer.

        If the buffer reaches flush_size, it will be flushed immediately.

        Args:
            event: The event dict to buffer
            execution_id: Optional execution ID to add
            phase_id: Optional phase ID to add
        """
        # Add context if provided
        if execution_id:
            event = {**event, "execution_id": execution_id}
        if phase_id:
            event = {**event, "phase_id": phase_id}

        async with self._lock:
            self._buffer.append(event)
            if len(self._buffer) >= self._flush_size:
                await self._flush_locked()

    async def add_many(
        self,
        events: list[dict[str, Any]],
        execution_id: str | None = None,
        phase_id: str | None = None,
    ) -> None:
        """Add multiple events to the buffer.

        Args:
            events: List of event dicts to buffer
            execution_id: Optional execution ID to add to all events
            phase_id: Optional phase ID to add to all events
        """
        # Add context if provided
        if execution_id or phase_id:
            enriched_events = []
            for event in events:
                enriched = event.copy()
                if execution_id:
                    enriched["execution_id"] = execution_id
                if phase_id:
                    enriched["phase_id"] = phase_id
                enriched_events.append(enriched)
            events = enriched_events

        async with self._lock:
            self._buffer.extend(events)
            while len(self._buffer) >= self._flush_size:
                await self._flush_locked()

    async def flush(self) -> int:
        """Flush all buffered events to the store.

        Returns:
            Number of events flushed
        """
        async with self._lock:
            return await self._flush_locked()

    async def _flush_locked(self) -> int:
        """Flush buffer while already holding the lock.

        Returns:
            Number of events flushed
        """
        if not self._buffer:
            return 0

        events = self._buffer
        self._buffer = []

        try:
            count = await self._store.insert_batch(events)
            self._total_events += count
            self._total_flushes += 1
            logger.debug("Flushed %d events (total: %d)", count, self._total_events)
            return count
        except Exception:
            # Put events back on failure
            self._buffer = events + self._buffer
            logger.exception("Failed to flush events, will retry")
            raise

    async def start(self) -> None:
        """Start the periodic flush task."""
        if self._running:
            return

        self._running = True
        self._flush_task = asyncio.create_task(self._periodic_flush())
        logger.info(
            "EventBuffer started (flush_size=%d, interval=%.2fs)",
            self._flush_size,
            self._flush_interval,
        )

    async def stop(self) -> None:
        """Stop the periodic flush task and flush remaining events."""
        self._running = False

        if self._flush_task:
            self._flush_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._flush_task
            self._flush_task = None

        # Flush any remaining events
        remaining = await self.flush()
        logger.info(
            "EventBuffer stopped (flushed %d remaining, total: %d events in %d flushes)",
            remaining,
            self._total_events,
            self._total_flushes,
        )

    async def _periodic_flush(self) -> None:
        """Periodically flush the buffer."""
        while self._running:
            await asyncio.sleep(self._flush_interval)
            if self._buffer:  # Only flush if there are events
                try:
                    await self.flush()
                except Exception:
                    # Log but don't crash the flush loop
                    logger.exception("Periodic flush failed")


def parse_jsonl_events(stdout: str) -> list[dict[str, Any]]:
    """Parse JSONL events from agent stdout.

    Args:
        stdout: Raw stdout from agent execution

    Returns:
        List of parsed event dicts
    """
    import json

    events = []
    for line in stdout.split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
            # Accept events with either 'type' or 'event_type'
            if isinstance(data, dict) and ("type" in data or "event_type" in data):
                # Normalize to event_type
                if "type" in data and "event_type" not in data:
                    data["event_type"] = data.pop("type")
                events.append(data)
        except json.JSONDecodeError:
            continue

    return events
