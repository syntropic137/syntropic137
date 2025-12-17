"""Tests for runner module.

Testing strategy:
- Unit tests (fast, <1s): Test parsing logic with mock SDK messages
- Integration tests (medium): Test event flow with mocked SDK
- E2E tests (slow): Validate real system - run sparingly

This file focuses on FAST unit tests that don't require Claude API calls.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from unittest import mock

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from aef_agent_runner.cancellation import CancellationToken
from aef_agent_runner.runner import AgentRunner
from aef_agent_runner.task import Task

# =============================================================================
# Mock SDK Message Types (for fast unit tests without Claude API)
# =============================================================================


@dataclass
class MockUsage:
    """Mock SDK Usage object."""

    input_tokens: int = 100
    output_tokens: int = 50
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0


@dataclass
class MockToolUseBlock:
    """Mock SDK ToolUseBlock - represents a tool being called."""

    type: str = "tool_use"
    id: str = "toolu_01abc123"
    name: str = "Bash"
    input: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if self.input is None:
            self.input = {"command": "ls -la"}


@dataclass
class MockToolResultBlock:
    """Mock SDK ToolResultBlock - represents a tool result."""

    type: str = "tool_result"
    tool_use_id: str = "toolu_01abc123"
    content: str = "file1.txt\nfile2.txt"
    is_error: bool = False


@dataclass
class MockTextBlock:
    """Mock SDK TextBlock."""

    type: str = "text"
    text: str = "I'll help you with that."


@dataclass
class MockAssistantMessage:
    """Mock SDK AssistantMessage with content blocks."""

    content: list[Any] | None = None
    usage: MockUsage | None = None

    def __post_init__(self) -> None:
        if self.content is None:
            self.content = []
        if self.usage is None:
            self.usage = MockUsage()


class TestAgentRunner:
    """Tests for AgentRunner class."""

    @pytest.fixture
    def task(self) -> Task:
        """Create a test task."""
        return Task(
            phase="test",
            prompt="Test the system",
            execution_id="exec-test-123",
            tenant_id="tenant-test",
            inputs={"key": "value"},
            artifacts=[],
        )

    @pytest.fixture
    def output_dir(self, tmp_path: Path) -> Path:
        """Create output directory."""
        out = tmp_path / "artifacts"
        out.mkdir()
        return out

    @pytest.fixture
    def cancel_token(self, tmp_path: Path) -> CancellationToken:
        """Create cancellation token."""
        return CancellationToken(tmp_path / ".cancel")

    def test_init(
        self,
        task: Task,
        output_dir: Path,
        cancel_token: CancellationToken,
    ) -> None:
        """Should initialize runner correctly."""
        runner = AgentRunner(
            task=task,
            output_dir=output_dir,
            cancel_token=cancel_token,
        )

        assert runner._task == task
        assert runner._output_dir == output_dir
        assert runner._cancel_token == cancel_token
        assert runner._turn_count == 0

    def test_init_creates_output_dir(
        self,
        task: Task,
        tmp_path: Path,
        cancel_token: CancellationToken,
    ) -> None:
        """Should create output directory if it doesn't exist."""
        output_dir = tmp_path / "new_artifacts"
        assert not output_dir.exists()

        AgentRunner(
            task=task,
            output_dir=output_dir,
            cancel_token=cancel_token,
        )

        assert output_dir.exists()

    def test_build_task_prompt(
        self,
        task: Task,
        output_dir: Path,
        cancel_token: CancellationToken,
    ) -> None:
        """Should build task prompt with task context."""
        runner = AgentRunner(
            task=task,
            output_dir=output_dir,
            cancel_token=cancel_token,
        )

        message = runner._build_task_prompt()

        # Prompt from task
        assert "Test the system" in message
        # Inputs section
        assert "key" in message
        assert "value" in message
        # Output instructions
        assert "/workspace/artifacts/" in message

    def test_collect_artifacts_emits_events(
        self,
        task: Task,
        output_dir: Path,
        cancel_token: CancellationToken,
    ) -> None:
        """Should emit artifact events for files in output dir."""
        # Create some output files
        (output_dir / "file1.md").write_text("# Test")
        (output_dir / "file2.json").write_text('{"key": "value"}')

        runner = AgentRunner(
            task=task,
            output_dir=output_dir,
            cancel_token=cancel_token,
        )

        # Collect and verify events are emitted
        with mock.patch("aef_agent_runner.runner.emit_artifact") as mock_emit:
            runner._collect_artifacts()

            assert mock_emit.call_count == 2

    def test_collect_artifacts_handles_subdirs(
        self,
        task: Task,
        output_dir: Path,
        cancel_token: CancellationToken,
    ) -> None:
        """Should handle files in subdirectories."""
        subdir = output_dir / "subdir"
        subdir.mkdir()
        (subdir / "nested.txt").write_text("nested content")

        runner = AgentRunner(
            task=task,
            output_dir=output_dir,
            cancel_token=cancel_token,
        )

        with mock.patch("aef_agent_runner.runner.emit_artifact") as mock_emit:
            runner._collect_artifacts()

            assert mock_emit.call_count == 1
            call_args = mock_emit.call_args
            assert "subdir/nested.txt" in call_args[1]["name"]


# =============================================================================
# FAST Unit Tests: Tool Message Parsing (no Claude API required)
# =============================================================================


class TestToolObservabilityParsing:
    """Test tool observability via SDK message parsing.

    These tests validate that _handle_assistant_message correctly:
    1. Parses ToolUseBlock and emits tool_use events
    2. Parses ToolResultBlock and emits tool_result events
    3. Maintains tool_use_id → tool_name mapping
    4. Handles both object and dict message formats

    All tests run in <1 second without Claude API calls.
    """

    @pytest.fixture
    def runner(self, tmp_path: Path) -> AgentRunner:
        """Create runner with minimal setup for unit testing."""
        task = Task(
            phase="test",
            prompt="Test prompt",
            execution_id="exec-test",
            tenant_id="tenant-test",
            inputs={},
            artifacts=[],
        )
        cancel_token = CancellationToken(tmp_path / ".cancel")
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        return AgentRunner(
            task=task,
            output_dir=output_dir,
            cancel_token=cancel_token,
        )

    def test_parses_tool_use_block_object(self, runner: AgentRunner) -> None:
        """Should parse ToolUseBlock object and emit tool_use event."""
        message = MockAssistantMessage(
            content=[
                MockTextBlock(text="I'll run a command"),
                MockToolUseBlock(
                    id="toolu_bash_001",
                    name="Bash",
                    input={"command": "git status"},
                ),
            ],
            usage=MockUsage(input_tokens=100, output_tokens=50),
        )

        with (
            mock.patch("aef_agent_runner.runner.emit_tool_use") as mock_tool_use,
            mock.patch("aef_agent_runner.runner.emit_token_usage"),
            mock.patch("aef_agent_runner.runner.emit_progress"),
        ):
            runner._handle_assistant_message(message)

            # Should emit tool_use event
            mock_tool_use.assert_called_once_with(
                tool_name="Bash",
                tool_input={"command": "git status"},
                tool_use_id="toolu_bash_001",
            )

            # Should store mapping for result lookup
            assert runner._tool_use_map["toolu_bash_001"] == "Bash"

    def test_parses_tool_use_block_dict_format(self, runner: AgentRunner) -> None:
        """Should parse ToolUseBlock dict format (fallback for older SDKs)."""
        message = MockAssistantMessage(
            content=[
                {
                    "type": "tool_use",
                    "id": "toolu_write_002",
                    "name": "Write",
                    "input": {"path": "/workspace/test.py", "content": "print('hi')"},
                },
            ],
            usage=MockUsage(),
        )

        with (
            mock.patch("aef_agent_runner.runner.emit_tool_use") as mock_tool_use,
            mock.patch("aef_agent_runner.runner.emit_token_usage"),
            mock.patch("aef_agent_runner.runner.emit_progress"),
        ):
            runner._handle_assistant_message(message)

            mock_tool_use.assert_called_once()
            call_kwargs = mock_tool_use.call_args[1]
            assert call_kwargs["tool_name"] == "Write"
            assert call_kwargs["tool_use_id"] == "toolu_write_002"

    def test_parses_tool_result_block_object(self, runner: AgentRunner) -> None:
        """Should parse ToolResultBlock object and emit tool_result event."""
        # First, add a tool to the map (simulating a prior ToolUseBlock)
        runner._tool_use_map["toolu_bash_001"] = "Bash"

        message = MockAssistantMessage(
            content=[
                MockToolResultBlock(
                    tool_use_id="toolu_bash_001",
                    content="README.md\nsetup.py",
                    is_error=False,
                ),
            ],
            usage=MockUsage(),
        )

        with (
            mock.patch("aef_agent_runner.runner.emit_tool_result") as mock_tool_result,
            mock.patch("aef_agent_runner.runner.emit_token_usage"),
            mock.patch("aef_agent_runner.runner.emit_progress"),
        ):
            runner._handle_assistant_message(message)

            mock_tool_result.assert_called_once_with(
                tool_name="Bash",  # Looked up from map
                success=True,
                tool_use_id="toolu_bash_001",
                duration_ms=None,
            )

    def test_parses_tool_result_block_dict_format(self, runner: AgentRunner) -> None:
        """Should parse ToolResultBlock dict format."""
        runner._tool_use_map["toolu_read_003"] = "Read"

        message = MockAssistantMessage(
            content=[
                {
                    "type": "tool_result",
                    "tool_use_id": "toolu_read_003",
                    "content": "file contents here",
                    "is_error": False,
                },
            ],
            usage=MockUsage(),
        )

        with (
            mock.patch("aef_agent_runner.runner.emit_tool_result") as mock_tool_result,
            mock.patch("aef_agent_runner.runner.emit_token_usage"),
            mock.patch("aef_agent_runner.runner.emit_progress"),
        ):
            runner._handle_assistant_message(message)

            mock_tool_result.assert_called_once()
            assert mock_tool_result.call_args[1]["tool_name"] == "Read"
            assert mock_tool_result.call_args[1]["success"] is True

    def test_parses_tool_result_error(self, runner: AgentRunner) -> None:
        """Should correctly report tool errors."""
        runner._tool_use_map["toolu_bash_fail"] = "Bash"

        message = MockAssistantMessage(
            content=[
                MockToolResultBlock(
                    tool_use_id="toolu_bash_fail",
                    content="command not found: invalid_command",
                    is_error=True,
                ),
            ],
            usage=MockUsage(),
        )

        with (
            mock.patch("aef_agent_runner.runner.emit_tool_result") as mock_tool_result,
            mock.patch("aef_agent_runner.runner.emit_token_usage"),
            mock.patch("aef_agent_runner.runner.emit_progress"),
        ):
            runner._handle_assistant_message(message)

            mock_tool_result.assert_called_once()
            assert mock_tool_result.call_args[1]["success"] is False

    def test_handles_unknown_tool_result(self, runner: AgentRunner) -> None:
        """Should handle tool_result for unknown tool_use_id gracefully."""
        # No entry in tool_use_map - simulates edge case
        message = MockAssistantMessage(
            content=[
                MockToolResultBlock(
                    tool_use_id="toolu_unknown_999",
                    content="some result",
                    is_error=False,
                ),
            ],
            usage=MockUsage(),
        )

        with (
            mock.patch("aef_agent_runner.runner.emit_tool_result") as mock_tool_result,
            mock.patch("aef_agent_runner.runner.emit_token_usage"),
            mock.patch("aef_agent_runner.runner.emit_progress"),
        ):
            runner._handle_assistant_message(message)

            # Should emit with "unknown" tool name
            mock_tool_result.assert_called_once()
            assert mock_tool_result.call_args[1]["tool_name"] == "unknown"

    def test_parses_multiple_tool_blocks(self, runner: AgentRunner) -> None:
        """Should parse multiple tool blocks in single message."""
        message = MockAssistantMessage(
            content=[
                MockTextBlock(text="Running multiple tools"),
                MockToolUseBlock(id="toolu_001", name="Bash", input={"command": "ls"}),
                MockToolUseBlock(id="toolu_002", name="Read", input={"path": "/test"}),
                MockToolUseBlock(id="toolu_003", name="Write", input={"path": "/out"}),
            ],
            usage=MockUsage(),
        )

        with (
            mock.patch("aef_agent_runner.runner.emit_tool_use") as mock_tool_use,
            mock.patch("aef_agent_runner.runner.emit_token_usage"),
            mock.patch("aef_agent_runner.runner.emit_progress"),
        ):
            runner._handle_assistant_message(message)

            # Should emit 3 tool_use events
            assert mock_tool_use.call_count == 3

            # All tools should be in map
            assert runner._tool_use_map["toolu_001"] == "Bash"
            assert runner._tool_use_map["toolu_002"] == "Read"
            assert runner._tool_use_map["toolu_003"] == "Write"

    def test_still_emits_token_usage(self, runner: AgentRunner) -> None:
        """Should still emit token_usage event (not just tools)."""
        message = MockAssistantMessage(
            content=[MockTextBlock(text="Just some text")],
            usage=MockUsage(
                input_tokens=150,
                output_tokens=75,
                cache_creation_input_tokens=10,
                cache_read_input_tokens=20,
            ),
        )

        with (
            mock.patch("aef_agent_runner.runner.emit_token_usage") as mock_token,
            mock.patch("aef_agent_runner.runner.emit_progress"),
        ):
            runner._handle_assistant_message(message)

            mock_token.assert_called_once_with(
                input_tokens=150,
                output_tokens=75,
                cache_creation_tokens=10,
                cache_read_tokens=20,
            )

    def test_emits_progress_update(self, runner: AgentRunner) -> None:
        """Should always emit progress update."""
        message = MockAssistantMessage(
            content=[],
            usage=MockUsage(),
        )

        with (
            mock.patch("aef_agent_runner.runner.emit_token_usage"),
            mock.patch("aef_agent_runner.runner.emit_progress") as mock_progress,
        ):
            runner._handle_assistant_message(message)

            mock_progress.assert_called_once()

    def test_full_tool_lifecycle(self, runner: AgentRunner) -> None:
        """Test complete tool lifecycle: use → result."""
        # Message 1: Tool use
        use_message = MockAssistantMessage(
            content=[
                MockToolUseBlock(
                    id="toolu_lifecycle_001",
                    name="Bash",
                    input={"command": "echo hello"},
                ),
            ],
            usage=MockUsage(input_tokens=50, output_tokens=25),
        )

        # Message 2: Tool result
        result_message = MockAssistantMessage(
            content=[
                MockToolResultBlock(
                    tool_use_id="toolu_lifecycle_001",
                    content="hello",
                    is_error=False,
                ),
            ],
            usage=MockUsage(input_tokens=30, output_tokens=10),
        )

        with (
            mock.patch("aef_agent_runner.runner.emit_tool_use") as mock_use,
            mock.patch("aef_agent_runner.runner.emit_tool_result") as mock_result,
            mock.patch("aef_agent_runner.runner.emit_token_usage"),
            mock.patch("aef_agent_runner.runner.emit_progress"),
        ):
            # Process use
            runner._handle_assistant_message(use_message)
            mock_use.assert_called_once()
            assert mock_use.call_args[1]["tool_name"] == "Bash"

            # Process result
            runner._handle_assistant_message(result_message)
            mock_result.assert_called_once()
            assert mock_result.call_args[1]["tool_name"] == "Bash"  # Looked up!
            assert mock_result.call_args[1]["success"] is True
