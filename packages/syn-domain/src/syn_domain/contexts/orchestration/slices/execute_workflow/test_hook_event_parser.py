"""Tests for HookEventParser."""

from __future__ import annotations

import json
from typing import Any

import pytest

from syn_domain.contexts.orchestration.slices.execute_workflow.HookEventParser import (
    HookEventParser,
)


def _hook_jsonl(event_type: str = "tool_execution_started", **extra: Any) -> str:
    """Build a valid hook JSONL line."""
    event: dict[str, Any] = {"event_type": event_type, "session_id": "s-1", "timestamp": "t1"}
    event.update(extra)
    return json.dumps(event)


@pytest.mark.unit
class TestHookEventParser:
    def test_standalone_jsonl_parsed(self) -> None:
        parser = HookEventParser()
        line = _hook_jsonl("tool_execution_started")
        events = parser.parse(line)
        assert len(events) == 1
        assert events[0]["event_type"] == "tool_execution_started"

    def test_hook_response_with_output_channel(self) -> None:
        parser = HookEventParser()
        embedded = _hook_jsonl("tool_execution_completed")
        line = json.dumps(
            {
                "type": "system",
                "subtype": "hook_response",
                "hook_name": "pre-commit",
                "hook_event": "after",
                "output": embedded,
                "stdout": "",
                "stderr": "",
            }
        )
        events = parser.parse(line)
        assert len(events) == 1
        assert events[0]["event_type"] == "tool_execution_completed"

    def test_hook_response_with_multiple_channels(self) -> None:
        parser = HookEventParser()
        evt1 = _hook_jsonl("tool_execution_started", context={"tool_use_id": "tu-1"})
        evt2 = _hook_jsonl("tool_execution_completed", context={"tool_use_id": "tu-2"})
        line = json.dumps(
            {
                "type": "system",
                "subtype": "hook_response",
                "hook_name": "test",
                "hook_event": "after",
                "output": evt1,
                "stdout": evt2,
                "stderr": "",
            }
        )
        events = parser.parse(line)
        assert len(events) == 2

    def test_deduplication_of_identical_fingerprints(self) -> None:
        parser = HookEventParser()
        line = _hook_jsonl("tool_execution_started")
        events1 = parser.parse(line)
        events2 = parser.parse(line)
        assert len(events1) == 1
        assert len(events2) == 0  # Duplicate suppressed

    def test_non_json_returns_empty(self) -> None:
        parser = HookEventParser()
        events = parser.parse("not json at all")
        assert events == []

    def test_cli_event_not_treated_as_hook(self) -> None:
        """Regular CLI events (type=assistant) are not hook events."""
        parser = HookEventParser()
        line = json.dumps({"type": "assistant", "message": {"content": []}})
        events = parser.parse(line)
        assert events == []

    def test_dedup_with_tool_use_id_uses_full_fingerprint(self) -> None:
        """Events with tool_use_id use (type, session, timestamp, tool_use_id) fingerprint."""
        parser = HookEventParser()
        line1 = _hook_jsonl(
            "tool_execution_started",
            context={"tool_use_id": "tu-1"},
        )
        line2 = _hook_jsonl(
            "tool_execution_started",
            context={"tool_use_id": "tu-2"},
        )
        events1 = parser.parse(line1)
        events2 = parser.parse(line2)
        assert len(events1) == 1
        assert len(events2) == 1  # Different tool_use_id → not a dupe
