"""Helper functions and singleton factory for AgentEventStore.

Extracted from store.py to reduce module complexity.
"""

from __future__ import annotations

import io
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from syn_adapters.events.models import AgentEvent

if TYPE_CHECKING:
    from syn_adapters.events.store import AgentEventStore

logger = logging.getLogger(__name__)


def _event_to_copy_row(validated: AgentEvent) -> str:
    """Convert a validated AgentEvent to a tab-separated COPY row."""
    time, event_type, session_id, exec_id, phase_id, data_json = (
        validated.to_insert_tuple()
    )
    row = [
        time.isoformat() if isinstance(time, datetime) else time,
        event_type,
        session_id or "unknown",
        exec_id or "\\N",
        phase_id or "\\N",
        data_json,
    ]
    return "\t".join(str(v) for v in row) + "\n"


def _build_copy_buffer(
    events: list[dict[str, Any]],
    execution_id: str | None,
    phase_id: str | None,
) -> io.BytesIO:
    """Build a BytesIO buffer of tab-separated rows for COPY."""
    buffer = io.BytesIO()
    for event in events:
        if execution_id and "execution_id" not in event:
            event = {**event, "execution_id": execution_id}
        if phase_id and "phase_id" not in event:
            event = {**event, "phase_id": phase_id}
        try:
            validated = AgentEvent.from_dict(event)
        except Exception as e:
            logger.warning("Skipping invalid event: %s", e)
            continue
        buffer.write(_event_to_copy_row(validated).encode("utf-8"))
    buffer.seek(0)
    return buffer


# Keys in the top-level event dict that must NOT be overridden by user data.
# AgentEvent.from_dict() uses "message" to detect Claude conversation messages,
# and the other keys are event metadata. Collisions silently corrupt stored events.
RESERVED_OBSERVATION_KEYS: frozenset[str] = frozenset(
    {
        "event_type",
        "type",
        "session_id",
        "execution_id",
        "phase_id",
        "workspace_id",
        "timestamp",
        "time",
        "id",
        # "message" is reserved: from_dict() calls message.get("content", []) to detect
        # Claude tool_use/tool_result content blocks. A string "message" value crashes it.
        "message",
    }
)


# Singleton instance (lazy-loaded)
_event_store: "AgentEventStore | None" = None


def get_event_store(connection_string: str | None = None) -> "AgentEventStore":
    """Get or create the AgentEventStore singleton.

    Uses SYN_OBSERVABILITY_DB_URL from settings (ADR-030 unified database).

    Args:
        connection_string: Optional connection string (uses settings if not provided)

    Returns:
        AgentEventStore instance

    Raises:
        ValueError: If SYN_OBSERVABILITY_DB_URL is not configured
    """
    from syn_adapters.events.store import AgentEventStore

    global _event_store

    if _event_store is None:
        if connection_string is None:
            from syn_shared.settings.config import get_settings

            settings = get_settings()

            if not settings.syn_observability_db_url:
                raise ValueError(
                    "SYN_OBSERVABILITY_DB_URL must be configured. "
                    "Set it in your .env file: "
                    "SYN_OBSERVABILITY_DB_URL=postgresql://user:pass@host:port/database"
                )

            connection_string = str(settings.syn_observability_db_url)

        _event_store = AgentEventStore(connection_string)

    return _event_store


async def insert_batch(
    store: "AgentEventStore",
    events: list[dict[str, Any]],
    execution_id: str | None = None,
    phase_id: str | None = None,
) -> int:
    """Insert a batch of events using COPY for maximum throughput.

    This is the recommended way to insert events - buffer them and
    insert in batches of 1000+ for best performance.

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

    buffer = _build_copy_buffer(events, execution_id, phase_id)

    async with store.pool.acquire() as conn:
        result = await conn.copy_to_table(
            "agent_events",
            source=buffer,
            columns=["time", "event_type", "session_id", "execution_id", "phase_id", "data"],
            format="text",
        )

    if isinstance(result, str) and result.startswith("COPY"):
        count = int(result.split()[1])
    else:
        count = len(events)

    logger.debug("Inserted %d events", count)
    return count


async def record_observation(
    store: "AgentEventStore",
    session_id: str,
    observation_type: str,
    data: dict[str, Any],
    execution_id: str | None = None,
    phase_id: str | None = None,
    workspace_id: str | None = None,
) -> None:
    """Record an observation event (ObservabilityWriter interface for ADR-026).

    This method adapts the WorkflowExecutionEngine's observability API
    to the AgentEventStore's insert_one method.

    Args:
        store: AgentEventStore instance
        session_id: Session ID
        observation_type: Type of observation (e.g., "token_usage", "tool_execution_started")
        data: Observation-specific payload. Must NOT contain reserved keys
              (event_type, session_id, message, timestamp, etc.) — they are
              silently dropped with a warning. Use field names specific to the
              observation type (e.g., "commit_message" not "message").
        execution_id: Optional execution ID
        phase_id: Optional phase ID
        workspace_id: Optional workspace ID
    """
    if conflicting := (data.keys() & RESERVED_OBSERVATION_KEYS):
        logger.warning(
            "record_observation(%s): data contains reserved keys %s — "
            "they will be ignored to prevent event corruption. "
            "Rename the field(s) in the caller.",
            observation_type,
            sorted(conflicting),
        )
    safe_data = {k: v for k, v in data.items() if k not in RESERVED_OBSERVATION_KEYS}
    event = {
        "event_type": observation_type,
        "session_id": session_id,
        "timestamp": datetime.now(UTC),
        "workspace_id": workspace_id,
        **safe_data,
    }
    # Lazy import to avoid circular dependency with store_write
    from syn_adapters.events.store_write import insert_one

    await insert_one(
        store,
        event=event,
        execution_id=execution_id,
        phase_id=phase_id,
    )
