"""Shared parsing utilities for JSONL file watchers.

Extracted from hooks.py and transcript.py to reduce duplication
and module complexity.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from syn_collector.events.types import CollectedEvent

logger = logging.getLogger(__name__)


class EventParser(Protocol):
    """Protocol for event-specific parsing callbacks."""

    def __call__(self, data: dict[str, Any]) -> CollectedEvent | None: ...


def parse_timestamp(timestamp_str: str | None) -> datetime:
    """Parse an ISO timestamp string, falling back to now(UTC)."""
    if timestamp_str:
        try:
            return datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
        except ValueError:
            pass
    return datetime.now(UTC)


def parse_jsonl_events(
    lines: list[str],
    parser: EventParser,
    *,
    source_label: str = "file",
) -> list[CollectedEvent]:
    """Parse a list of JSONL lines into events using the provided parser.

    Args:
        lines: Raw JSONL line strings (already stripped).
        parser: Callable that converts a JSON dict to a CollectedEvent or None.
        source_label: Label for log messages (e.g. "hook file", "transcript").

    Returns:
        List of successfully parsed events.
    """
    events: list[CollectedEvent] = []
    for line_content in lines:
        try:
            data = json.loads(line_content)
            event = parser(data)
            if event:
                events.append(event)
        except json.JSONDecodeError as e:
            logger.warning(
                f"Invalid JSON in {source_label}: {e}", extra={"line": line_content[:100]}
            )
        except Exception as e:
            logger.warning(
                f"Failed to parse {source_label} event: {e}", extra={"line": line_content[:100]}
            )
    return events
