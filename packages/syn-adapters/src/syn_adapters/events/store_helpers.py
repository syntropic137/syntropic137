"""Helper functions and singleton factory for AgentEventStore.

Extracted from store.py to reduce module complexity.
"""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from syn_adapters.events.models import AgentEvent
from syn_adapters.postgres_text import pg_copy_row
from syn_domain import tool_call_counts

if TYPE_CHECKING:
    from syn_adapters.events.store import AgentEventStore

logger = logging.getLogger(__name__)


#: What an event that carries no session at all is stored under. Not an id:
#: no session lookup asks for it. See ``_event_to_copy_row``.
NO_SESSION_ID = "unknown"


def _event_to_copy_row(validated: AgentEvent) -> str:
    """Render a validated AgentEvent as one row of COPY text format.

    Every field here is agent- or harness-supplied, so any of them can contain
    the characters COPY reads as framing - a tab in a session id splits it into
    two columns, and the backslashes JSON writes its own escapes with are eaten
    before the payload reaches the jsonb parser (#1241). pg_copy_row owns that;
    this function only says which value goes in which column.

    It says only that, for every value that IS one. The ids arrive canonical
    from ``to_insert_tuple`` and go through unchanged, because this is the batch
    spelling of a row ``insert_one`` also writes: a serializer that substitutes
    an id of its own makes the two writers disagree, and then which path an
    event happened to take decides whether a reader ever finds it again. An id
    made entirely of unstorable codepoints used to arrive here as ``""`` and be
    stored as ``"unknown"`` for exactly that reason. It no longer arrives that
    way - ``pg_safe`` derives a real id for it - so the substitution below can
    no longer reach an id, and is written as an explicit ``is None`` rather than
    ``or`` so that it cannot start reaching one again if an empty id ever
    becomes representable.

    ``None`` is not an id, and is the one case left: the event carried no
    session at all. ``session_id`` is ``NOT NULL``, and COPY applies the whole
    buffer as one statement, so writing NULL here would fail the entire batch -
    discarding every valid event beside it - to reject one event that is still
    worth keeping, because its ``execution_id`` is intact and the cost, totals
    and heatmap readers key on that column alone. It is stored under a name no
    session lookup asks for, which is the truth about it: it has no session.
    """
    time, event_type, session_id, exec_id, phase_id, data_json = validated.to_insert_tuple()
    return pg_copy_row(
        [
            time.isoformat(),
            event_type,
            session_id if session_id is not None else NO_SESSION_ID,
            exec_id,
            phase_id,
            data_json,
        ]
    )


@dataclass(frozen=True)
class CopyPayload:
    """One batch, ready to write: the COPY rows and the tool calls they add.

    The two travel together because they are counted from the same validated
    events, in the same pass, and are applied in the same transaction. An event
    that failed validation is in neither, which is the only reason the tally
    cannot be taken from ``events`` by the caller instead (#1322).
    """

    buffer: io.BytesIO
    tool_calls: list[tool_call_counts.ToolCallTally]


def _build_copy_buffer(
    events: list[dict[str, Any]],
    execution_id: str | None,
    phase_id: str | None,
) -> CopyPayload:
    """Build the COPY buffer for a batch, and tally the tool calls in it."""
    buffer = io.BytesIO()
    counted: list[tuple[str, str, str | None]] = []
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
        # From the insert tuple, not from `event`: the stored spelling of the
        # ids and the normalised event type are decided there, and a tally
        # keyed by anything else is a tally no reader will ever find (#1241).
        _time, row_type, row_session, row_exec, _phase, _data = validated.to_insert_tuple()
        counted.append(
            (row_type, row_session if row_session is not None else NO_SESSION_ID, row_exec)
        )
    buffer.seek(0)
    return CopyPayload(buffer=buffer, tool_calls=tool_call_counts.tally(counted))


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
_event_store: AgentEventStore | None = None


def get_event_store(connection_string: str | None = None) -> AgentEventStore:
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


async def record_observation(
    store: AgentEventStore,
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
