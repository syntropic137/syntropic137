"""Flush/drain logic and utilities for EventBuffer.

Extracted from buffer.py to reduce module complexity.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from syn_adapters.events.parse import parse_jsonl_events as parse_jsonl_events

if TYPE_CHECKING:
    from syn_adapters.events.buffer import EventBuffer

logger = logging.getLogger(__name__)


async def flush_locked(buffer: EventBuffer) -> int:
    """Flush buffer while already holding the lock.

    Returns:
        Number of events flushed
    """
    if not buffer._buffer:
        return 0

    events = buffer._buffer
    buffer._buffer = []

    try:
        count = await buffer._store.insert_batch(events)
        buffer._total_events += count
        buffer._total_flushes += 1
        logger.debug("Flushed %d events (total: %d)", count, buffer._total_events)
        return count
    except Exception:
        # Put events back on failure
        buffer._buffer = events + buffer._buffer
        logger.exception("Failed to flush events, will retry")
        raise


async def periodic_flush(buffer: EventBuffer) -> None:
    """Periodically flush the buffer."""
    import asyncio

    while buffer._running:
        await asyncio.sleep(buffer._flush_interval)
        if buffer._buffer:  # Only flush if there are events
            try:
                await buffer.flush()
            except Exception:
                # Log but don't crash the flush loop
                logger.exception("Periodic flush failed")


# Singleton event buffer
_event_buffer: EventBuffer | None = None


async def get_event_buffer() -> EventBuffer:
    """Get or create singleton EventBuffer.

    Creates and starts an EventBuffer connected to the singleton AgentEventStore.
    The buffer is started automatically on first access.

    Returns:
        Singleton EventBuffer instance
    """
    from syn_adapters.events.buffer import EventBuffer
    from syn_adapters.events.store import get_event_store

    global _event_buffer

    if _event_buffer is None:
        store = get_event_store()
        await store.initialize()
        _event_buffer = EventBuffer(store)
        await _event_buffer.start()

    return _event_buffer
