"""Tests for SubagentTracker."""

from __future__ import annotations

from syn_domain.contexts.orchestration.slices.execute_workflow.SubagentTracker import (
    SubagentTracker,
)


class TestSubagentTracker:
    def test_initial_state(self) -> None:
        tracker = SubagentTracker()
        assert not tracker.has_active

    def test_register_and_resolve_tool(self) -> None:
        tracker = SubagentTracker()
        tracker.register_tool_use("id-1", "Read")
        assert tracker.resolve_tool_name("id-1") == "Read"
        assert tracker.resolve_tool_name("unknown-id") == "unknown"

    def test_task_lifecycle(self) -> None:
        tracker = SubagentTracker()
        started = tracker.on_task_started("task-1", {"subagent_type": "test-agent"})
        assert started.agent_name == "test-agent"
        assert started.event_type == "started"
        assert tracker.has_active

        stopped = tracker.on_task_completed("task-1", success=True)
        assert stopped is not None
        assert stopped.agent_name == "test-agent"
        assert stopped.event_type == "stopped"
        assert stopped.success is True
        assert stopped.duration_ms is not None
        assert not tracker.has_active

    def test_task_completed_unknown_id(self) -> None:
        tracker = SubagentTracker()
        result = tracker.on_task_completed("unknown", success=True)
        assert result is None

    def test_hook_started(self) -> None:
        tracker = SubagentTracker()
        import json

        preview = json.dumps({"subagent_type": "explore"})
        event = tracker.on_task_started_from_hook("task-2", preview)
        assert event.agent_name == "explore"
        assert tracker.has_active

    def test_hook_started_invalid_json(self) -> None:
        tracker = SubagentTracker()
        event = tracker.on_task_started_from_hook("task-3", "not-json")
        assert event.agent_name == "unknown"

    def test_attribute_tool(self) -> None:
        tracker = SubagentTracker()
        tracker.on_task_started("task-1", {"description": "agent-a"})
        tracker.attribute_tool("Read")
        tracker.attribute_tool("Read")
        tracker.attribute_tool("Write")

        stopped = tracker.on_task_completed("task-1", success=True)
        assert stopped is not None
        assert stopped.tools_used == {"Read": 2, "Write": 1}

    def test_attribute_tool_no_active(self) -> None:
        tracker = SubagentTracker()
        # Should not raise
        tracker.attribute_tool("Read")

    def test_agent_name_truncated(self) -> None:
        tracker = SubagentTracker()
        long_name = "a" * 100
        event = tracker.on_task_started("task-1", {"subagent_type": long_name})
        assert len(event.agent_name) == 50
