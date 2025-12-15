"""Tests for agentic types - AgentEvent, AgentExecutionConfig, etc."""

from datetime import datetime
from pathlib import Path

import pytest

from aef_adapters.agents.agentic_types import (
    AgentExecutionConfig,
    AgentExecutionResult,
    AgentTool,
    TaskCompleted,
    TaskFailed,
    TextOutput,
    ThinkingUpdate,
    ToolBlocked,
    ToolUseCompleted,
    ToolUseStarted,
    Workspace,
    WorkspaceConfig,
)


class TestAgentTool:
    """Tests for AgentTool enum."""

    def test_all_returns_all_tool_names(self) -> None:
        """All tools should be returned as strings."""
        tools = AgentTool.all()
        assert "Read" in tools
        assert "Write" in tools
        assert "Bash" in tools
        assert len(tools) == len(AgentTool)

    def test_file_tools_returns_file_operations(self) -> None:
        """File tools should include CRUD operations."""
        file_tools = AgentTool.file_tools()
        assert "Read" in file_tools
        assert "Write" in file_tools
        assert "Edit" in file_tools
        assert "MultiEdit" in file_tools
        assert "Bash" not in file_tools

    def test_safe_tools_are_read_only(self) -> None:
        """Safe tools should be read-only operations."""
        safe = AgentTool.safe_tools()
        assert "Read" in safe
        assert "LS" in safe
        assert "Glob" in safe
        assert "Grep" in safe
        # Write operations should NOT be safe
        assert "Write" not in safe
        assert "Edit" not in safe
        assert "Bash" not in safe


class TestAgentExecutionConfig:
    """Tests for AgentExecutionConfig."""

    def test_default_config_allows_all_tools(self) -> None:
        """Default config should allow all tools."""
        config = AgentExecutionConfig()
        assert config.allowed_tools == frozenset(AgentTool.all())

    def test_default_limits(self) -> None:
        """Default limits should be reasonable."""
        config = AgentExecutionConfig()
        assert config.max_turns == 25
        assert config.max_budget_usd is None
        assert config.timeout_seconds == 600

    def test_with_tools_creates_new_config(self) -> None:
        """with_tools should create a new config with specified tools."""
        original = AgentExecutionConfig(max_turns=10)
        restricted = original.with_tools({"Read", "LS"})

        # New config has restricted tools
        assert restricted.allowed_tools == frozenset({"Read", "LS"})
        # Other settings preserved
        assert restricted.max_turns == 10
        # Original unchanged
        assert original.allowed_tools == frozenset(AgentTool.all())

    def test_with_budget_creates_new_config(self) -> None:
        """with_budget should create a new config with budget limit."""
        original = AgentExecutionConfig()
        budgeted = original.with_budget(1.50)

        assert budgeted.max_budget_usd == 1.50
        assert original.max_budget_usd is None

    def test_config_is_immutable(self) -> None:
        """Config should be frozen (immutable)."""
        config = AgentExecutionConfig()
        with pytest.raises(AttributeError):
            config.max_turns = 100  # type: ignore[misc]


class TestAgentEvents:
    """Tests for AgentEvent types."""

    def test_tool_use_started_has_correct_event_type(self) -> None:
        """ToolUseStarted should have correct event_type."""
        event = ToolUseStarted(
            tool_name="Write",
            tool_input={"path": "test.py", "content": "print('hi')"},
            tool_use_id="123",
        )
        assert event.event_type == "tool_use_started"
        assert event.tool_name == "Write"
        assert event.tool_input["path"] == "test.py"

    def test_tool_use_completed_tracks_duration(self) -> None:
        """ToolUseCompleted should track duration and success."""
        event = ToolUseCompleted(
            tool_name="Read",
            tool_use_id="123",
            tool_output="file contents",
            duration_ms=42.5,
            success=True,
        )
        assert event.event_type == "tool_use_completed"
        assert event.duration_ms == 42.5
        assert event.success is True
        assert event.error is None

    def test_tool_blocked_captures_reason(self) -> None:
        """ToolBlocked should capture reason and validator."""
        event = ToolBlocked(
            tool_name="Bash",
            reason="Dangerous command: rm -rf /",
            validator="security.bash",
        )
        assert event.event_type == "tool_blocked"
        assert "rm -rf" in event.reason
        assert event.validator == "security.bash"

    def test_thinking_update_captures_content(self) -> None:
        """ThinkingUpdate should capture thinking content."""
        event = ThinkingUpdate(content="Let me analyze this...")
        assert event.event_type == "thinking_update"
        assert event.content == "Let me analyze this..."

    def test_text_output_tracks_partial_flag(self) -> None:
        """TextOutput should track if content is partial."""
        partial = TextOutput(content="Starting...", is_partial=True)
        final = TextOutput(content="Done!", is_partial=False)

        assert partial.is_partial is True
        assert final.is_partial is False

    def test_task_completed_includes_metrics(self) -> None:
        """TaskCompleted should include all metrics."""
        event = TaskCompleted(
            result="Task completed successfully",
            input_tokens=1000,
            output_tokens=500,
            total_tokens=1500,
            turns_used=5,
            tools_used=["Read", "Write"],
            duration_ms=5000.0,
            estimated_cost_usd=0.05,
        )
        assert event.event_type == "task_completed"
        assert event.total_tokens == 1500
        assert event.turns_used == 5
        assert "Write" in event.tools_used

    def test_task_failed_includes_error_info(self) -> None:
        """TaskFailed should include error details."""
        event = TaskFailed(
            error="API rate limit exceeded",
            error_type="rate_limit",
            partial_result="Started writing file...",
            turns_used=3,
        )
        assert event.event_type == "task_failed"
        assert "rate limit" in event.error
        assert event.error_type == "rate_limit"
        assert event.partial_result is not None

    def test_events_have_timestamps(self) -> None:
        """All events should have timestamps."""
        events = [
            ToolUseStarted(tool_name="Read"),
            ToolUseCompleted(tool_name="Read"),
            ToolBlocked(tool_name="Bash", reason="blocked"),
            ThinkingUpdate(content="thinking"),
            TextOutput(content="output"),
            TaskCompleted(result="done"),
            TaskFailed(error="failed"),
        ]
        for event in events:
            assert isinstance(event.timestamp, datetime)


class TestWorkspace:
    """Tests for Workspace and WorkspaceConfig."""

    def test_workspace_config_requires_session_id(self) -> None:
        """WorkspaceConfig should require session_id."""
        config = WorkspaceConfig(session_id="test-123")
        assert config.session_id == "test-123"

    def test_workspace_config_has_defaults(self) -> None:
        """WorkspaceConfig should have sensible defaults."""
        config = WorkspaceConfig(session_id="test")
        assert config.analytics_path == ".agentic/analytics/events.jsonl"
        assert config.cleanup_on_exit is True

    def test_workspace_paths_are_derived(self) -> None:
        """Workspace should derive paths from base path."""
        config = WorkspaceConfig(session_id="test-123")
        workspace = Workspace(path=Path("/tmp/workspace"), config=config)

        assert workspace.analytics_path == Path("/tmp/workspace/.agentic/analytics/events.jsonl")
        assert workspace.context_dir == Path("/tmp/workspace/.context")
        assert workspace.output_dir == Path("/tmp/workspace/artifacts")
        assert workspace.hooks_dir == Path("/tmp/workspace/.claude/hooks")


class TestAgentExecutionResult:
    """Tests for AgentExecutionResult."""

    def test_result_aggregates_tool_usage(self) -> None:
        """Result should aggregate tool usage from events."""
        result = AgentExecutionResult(
            task="Test task",
            session_id="test-123",
            success=False,  # Will be updated
            result="",
        )

        # Add some events
        result.add_event(ToolUseCompleted(tool_name="Read", tool_use_id="1"))
        result.add_event(ToolUseCompleted(tool_name="Read", tool_use_id="2"))
        result.add_event(ToolUseCompleted(tool_name="Write", tool_use_id="3"))
        result.add_event(ToolBlocked(tool_name="Bash", reason="blocked"))

        assert result.tools_used == {"Read": 2, "Write": 1}
        assert result.tool_call_count == 3
        assert "Bash" in result.tools_blocked

    def test_result_updates_on_task_completed(self) -> None:
        """Result should update metrics when TaskCompleted is added."""
        result = AgentExecutionResult(
            task="Test task",
            session_id="test-123",
            success=False,
            result="",
        )

        result.add_event(
            TaskCompleted(
                result="Success!",
                input_tokens=1000,
                output_tokens=500,
                total_tokens=1500,
                turns_used=5,
                duration_ms=3000.0,
                estimated_cost_usd=0.05,
            )
        )

        assert result.success is True
        assert result.result == "Success!"
        assert result.total_tokens == 1500
        assert result.estimated_cost_usd == 0.05

    def test_result_updates_on_task_failed(self) -> None:
        """Result should update when TaskFailed is added."""
        result = AgentExecutionResult(
            task="Test task",
            session_id="test-123",
            success=True,  # Will be updated to False
            result="",
        )

        result.add_event(
            TaskFailed(
                error="Something went wrong",
                turns_used=2,
                input_tokens=500,
            )
        )

        assert result.success is False
        assert result.error == "Something went wrong"
        assert result.turns_used == 2
