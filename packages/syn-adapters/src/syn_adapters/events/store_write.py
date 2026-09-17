"""Write operations (insert_one) for AgentEventStore.

Extracted from store.py to reduce module complexity.
insert_batch and record_observation are in store_helpers.py.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from syn_adapters.events.models import AgentEvent
from syn_adapters.events.store_helpers import _build_copy_buffer
from syn_domain import tool_call_counts

if TYPE_CHECKING:
    from syn_adapters.events.store import AgentEventStore

logger = logging.getLogger(__name__)


class EventValidationError(Exception):
    """Raised when event data fails validation."""

    pass


async def insert_one(
    store: AgentEventStore,
    event: dict[str, Any],
    execution_id: str | None = None,
    phase_id: str | None = None,
) -> None:
    """Insert a single event with type validation.

    For high-throughput, prefer insert_batch().

    Uses AgentEvent model for type validation before insert.
    This catches type mismatches at runtime with clear error messages.

    Args:
        store: AgentEventStore instance
        event: Event dict with at least 'event_type' and 'session_id'
        execution_id: Optional execution ID
        phase_id: Optional phase ID

    Raises:
        EventValidationError: If event data fails validation
    """
    if not store._initialized:
        await store.initialize()

    if store.pool is None:
        raise RuntimeError("AgentEventStore pool is not initialized")

    # Add context IDs if not present
    if execution_id and "execution_id" not in event:
        event["execution_id"] = execution_id
    if phase_id and "phase_id" not in event:
        event["phase_id"] = phase_id

    # Validate through model (type-safe!)
    try:
        validated = AgentEvent.from_dict(event)
    except ValidationError as e:
        raise EventValidationError(f"Event validation failed: {e}") from e

    # Get insert tuple from validated model
    time, event_type, session_id, exec_id, ph_id, data_json = validated.to_insert_tuple()

    async with store.pool.acquire() as conn, conn.transaction():
        await conn.execute(
            """
            INSERT INTO agent_events
            (time, event_type, session_id, execution_id, phase_id, data)
            VALUES ($1, $2, $3, $4, $5, $6)
            """,
            time,
            event_type,
            session_id,
            exec_id,
            ph_id,
            data_json,
        )
        # In the SAME transaction as the row it counts. The tally is what the
        # list endpoints read instead of counting compressed chunks (#1322), so
        # a tally that can be written without its event - or an event without
        # its tally - is a number that drifts and never comes back.
        #
        # WHY assert: session_id is NOT NULL, so the INSERT above has already
        # raised for a None. Unlike the COPY path there is no whole batch to
        # save by substituting a name, and inventing one here would record a
        # tool call against a session that never existed.
        assert session_id is not None
        await tool_call_counts.record(
            conn, tool_call_counts.tally([(event_type, session_id, exec_id)])
        )


async def insert_batch(
    store: AgentEventStore,
    events: list[dict[str, Any]],
    execution_id: str | None = None,
    phase_id: str | None = None,
) -> int:
    """Insert a batch of events using COPY for maximum throughput.

    Args:
        store: AgentEventStore instance
        events: List of event dicts with at least 'event_type' and 'session_id'
        execution_id: Optional execution ID to add to all events
        phase_id: Optional phase ID to add to all events

    Returns:
        Number of events inserted
    """
    if not events:
        return 0

    if not store._initialized:
        await store.initialize()

    if store.pool is None:
        raise RuntimeError("AgentEventStore pool is not initialized")

    payload = _build_copy_buffer(events, execution_id, phase_id)

    async with store.pool.acquire() as conn, conn.transaction():
        result = await conn.copy_to_table(
            "agent_events",
            source=payload.buffer,
            columns=["time", "event_type", "session_id", "execution_id", "phase_id", "data"],
            format="text",
        )
        # Same transaction as the COPY, for the same reason as in insert_one.
        await tool_call_counts.record(conn, payload.tool_calls)

    if isinstance(result, str) and result.startswith("COPY"):
        count = int(result.split()[1])
    else:
        count = len(events)

    logger.debug("Inserted %d events", count)
    return count
