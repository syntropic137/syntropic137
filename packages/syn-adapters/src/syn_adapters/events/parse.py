"""JSONL parsing utilities for agent event streams.

Extracted from buffer_flush.py to reduce module complexity.
"""

from __future__ import annotations

import json
from typing import Any


def parse_jsonl_events(stdout: str) -> list[dict[str, Any]]:
    """Parse JSONL events from agent stdout.

    Args:
        stdout: Raw stdout from agent execution

    Returns:
        List of parsed event dicts
    """
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
