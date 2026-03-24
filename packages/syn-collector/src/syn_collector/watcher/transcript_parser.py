"""Transcript message parsing logic.

Extracted from TranscriptWatcher to reduce module complexity.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from syn_collector.events.ids import generate_token_event_id
from syn_collector.events.types import CollectedEvent, EventType
from syn_collector.watcher.parsing import parse_timestamp

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)


def parse_transcript_message(
    data: dict[str, Any],
    file_path: Path,
    session_id_override: str | None = None,
) -> CollectedEvent | None:
    """Parse a transcript message for token usage.

    Only processes 'assistant' type messages with usage data.

    Args:
        data: Raw JSON data from transcript.
        file_path: Source file for session ID extraction fallback.
        session_id_override: Fallback session ID.

    Returns:
        CollectedEvent or None if no usage data.
    """
    if data.get("type") != "assistant":
        return None

    usage = data.get("message", {}).get("usage")
    if not usage:
        return None

    message_uuid = data.get("uuid", "")
    if not message_uuid:
        logger.debug("Assistant message missing UUID")
        return None

    session_id = resolve_session_id(data, file_path, session_id_override)
    if not session_id:
        logger.warning("Transcript message missing sessionId")
        return None

    timestamp = parse_timestamp(data.get("timestamp"))
    event_id = generate_token_event_id(session_id, timestamp, message_uuid)

    event_data = {
        "message_uuid": message_uuid,
        "input_tokens": usage.get("input_tokens", 0),
        "output_tokens": usage.get("output_tokens", 0),
        "cache_creation_input_tokens": usage.get("cache_creation_input_tokens", 0),
        "cache_read_input_tokens": usage.get("cache_read_input_tokens", 0),
    }

    return CollectedEvent(
        event_id=event_id,
        event_type=EventType.TOKEN_USAGE,
        session_id=session_id,
        timestamp=timestamp,
        data=event_data,
    )


def resolve_session_id(
    data: dict[str, Any],
    file_path: Path,
    session_id_override: str | None = None,
) -> str | None:
    """Resolve session ID from data, override, or file path."""
    session_id = data.get("sessionId") or session_id_override
    if session_id:
        return session_id
    stem = file_path.stem
    if stem and len(stem) > 8:
        return stem
    return None
