"""Tool content extractors for AgentEvent model parsing.

Extracted from models.py to reduce module complexity.
"""

from __future__ import annotations

import json
from typing import Any


def _extract_tool_use(item: dict[str, Any], event_data: dict[str, Any]) -> None:
    """Extract fields from a tool_use content item (assistant message)."""
    if "tool_name" not in event_data:
        event_data["tool_name"] = item.get("name")
    if "tool_use_id" not in event_data:
        event_data["tool_use_id"] = item.get("id")
    if "input_preview" not in event_data:
        tool_input = item.get("input")
        if tool_input:
            event_data["input_preview"] = json.dumps(tool_input)[:500]


def _extract_tool_result(item: dict[str, Any], event_data: dict[str, Any]) -> None:
    """Extract fields from a tool_result content item (user message)."""
    if "tool_use_id" not in event_data:
        event_data["tool_use_id"] = item.get("tool_use_id")
    if "tool_name" not in event_data and "tool_name" in item:
        event_data["tool_name"] = item["tool_name"]
    if "success" not in event_data:
        event_data["success"] = not item.get("is_error", False)
