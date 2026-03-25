"""JSONL parsing utilities for agent event streams.

Extracted from buffer_flush.py to reduce module complexity.
"""

from __future__ import annotations

import json
from typing import Any


def _parse_line(line: str) -> dict[str, Any] | None:
    """Parse a single JSONL line, returning a normalized event dict or None."""
    line = line.strip()
    if not line:
        return None
    try:
        data = json.loads(line)
    except json.JSONDecodeError:
        return None

    if not isinstance(data, dict):
        return None
    if "type" not in data and "event_type" not in data:
        return None

    # Normalize to event_type
    if "type" in data and "event_type" not in data:
        data["event_type"] = data.pop("type")
    return data


def parse_jsonl_events(stdout: str) -> list[dict[str, Any]]:
    """Parse JSONL events from agent stdout.

    Args:
        stdout: Raw stdout from agent execution

    Returns:
        List of parsed event dicts
    """
    events: list[dict[str, Any]] = []
    for line in stdout.split("\n"):
        parsed = _parse_line(line)
        if parsed is not None:
            events.append(parsed)
    return events
