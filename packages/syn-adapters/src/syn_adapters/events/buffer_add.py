"""Add operations (add, add_many) for EventBuffer.

Extracted from buffer.py to reduce module complexity.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from syn_adapters.events.buffer import EventBuffer


async def add(
    buffer: EventBuffer,
    event: dict[str, Any],
    execution_id: str | None = None,
    phase_id: str | None = None,
) -> None:
    """Add an event to the buffer.

    If the buffer reaches flush_size, it will be flushed immediately.

    Args:
        buffer: EventBuffer instance
        event: The event dict to buffer
        execution_id: Optional execution ID to add
        phase_id: Optional phase ID to add
    """
    # Add context if provided
    if execution_id:
        event = {**event, "execution_id": execution_id}
    if phase_id:
        event = {**event, "phase_id": phase_id}

    async with buffer._lock:
        buffer._buffer.append(event)
        if len(buffer._buffer) >= buffer._flush_size:
            await buffer._flush_locked()


def _enrich_event(
    event: dict[str, Any],
    execution_id: str | None,
    phase_id: str | None,
) -> dict[str, Any]:
    """Return a copy of *event* with execution/phase context added."""
    enriched = event.copy()
    if execution_id:
        enriched["execution_id"] = execution_id
    if phase_id:
        enriched["phase_id"] = phase_id
    return enriched


async def add_many(
    buffer: EventBuffer,
    events: list[dict[str, Any]],
    execution_id: str | None = None,
    phase_id: str | None = None,
) -> None:
    """Add multiple events to the buffer.

    Args:
        buffer: EventBuffer instance
        events: List of event dicts to buffer
        execution_id: Optional execution ID to add to all events
        phase_id: Optional phase ID to add to all events
    """
    if execution_id or phase_id:
        events = [_enrich_event(e, execution_id, phase_id) for e in events]

    async with buffer._lock:
        buffer._buffer.extend(events)
        while len(buffer._buffer) >= buffer._flush_size:
            await buffer._flush_locked()
