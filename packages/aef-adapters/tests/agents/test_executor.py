"""Tests for AgentExecutor protocol and implementations.

See ADR-023: Workspace-First Execution Model
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import pytest

from aef_adapters.agents.executor import (
    AgentBudgetExceededError,
    AgentExecutionError,
    AgentExecutionMetrics,
    AgentNotAvailableError,
    ExecutionCompleted,
    ExecutionOutput,
    ExecutionProgress,
    ExecutionStarted,
    ExecutionToolUse,
    WorkspaceExecutionResult,
)


class TestAgentExecutionMetrics:
    """Tests for AgentExecutionMetrics dataclass."""

    def test_default_values(self) -> None:
        """Metrics should have sensible defaults."""
        metrics = AgentExecutionMetrics()

        assert metrics.input_tokens == 0
        assert metrics.output_tokens == 0
        assert metrics.total_tokens == 0
        assert metrics.turns_used == 0
        assert metrics.duration_seconds == 0.0
        assert metrics.estimated_cost_usd is None
        assert metrics.tools_used == []

    def test_with_values(self) -> None:
        """Metrics should accept values."""
        metrics = AgentExecutionMetrics(
            input_tokens=100,
            output_tokens=200,
            total_tokens=300,
            turns_used=5,
            duration_seconds=10.5,
            estimated_cost_usd=Decimal("0.05"),
            tools_used=["Read", "Write"],
        )

        assert metrics.input_tokens == 100
        assert metrics.output_tokens == 200
        assert metrics.total_tokens == 300
        assert metrics.turns_used == 5
        assert metrics.duration_seconds == 10.5
        assert metrics.estimated_cost_usd == Decimal("0.05")
        assert metrics.tools_used == ["Read", "Write"]


class TestWorkspaceExecutionResult:
    """Tests for WorkspaceExecutionResult dataclass."""

    def test_success_result(self) -> None:
        """Test successful result creation."""
        result = WorkspaceExecutionResult(
            success=True,
            output="Task completed",
            workspace_id="ws-123",
            execution_id="exec-456",
        )

        assert result.success is True
        assert result.output == "Task completed"
        assert result.error_message is None
        assert result.workspace_id == "ws-123"
        assert result.execution_id == "exec-456"

    def test_failure_result(self) -> None:
        """Test failure result creation."""
        result = WorkspaceExecutionResult(
            success=False,
            output="",
            error_message="Agent timed out",
        )

        assert result.success is False
        assert result.error_message == "Agent timed out"


class TestExecutionEvents:
    """Tests for ExecutionEvent types."""

    def test_execution_started(self) -> None:
        """Test ExecutionStarted event."""
        event = ExecutionStarted(
            workspace_id="ws-123",
            task="Create a file",
        )

        assert event.workspace_id == "ws-123"
        assert event.task == "Create a file"
        assert event.timestamp is not None

    def test_execution_progress(self) -> None:
        """Test ExecutionProgress event."""
        event = ExecutionProgress(
            message="Turn 1 completed",
            turn_number=1,
            tokens_used=150,
        )

        assert event.message == "Turn 1 completed"
        assert event.turn_number == 1
        assert event.tokens_used == 150

    def test_execution_output(self) -> None:
        """Test ExecutionOutput event."""
        event = ExecutionOutput(
            content="Hello, world!",
            is_partial=True,
        )

        assert event.content == "Hello, world!"
        assert event.is_partial is True

    def test_execution_tool_use(self) -> None:
        """Test ExecutionToolUse event."""
        event = ExecutionToolUse(
            tool_name="Write",
            tool_input={"path": "test.py", "content": "print('hi')"},
            success=True,
        )

        assert event.tool_name == "Write"
        assert event.tool_input == {"path": "test.py", "content": "print('hi')"}
        assert event.success is True

    def test_execution_completed(self) -> None:
        """Test ExecutionCompleted event."""
        result = WorkspaceExecutionResult(
            success=True,
            output="Done",
        )
        event = ExecutionCompleted(result=result)

        assert event.result.success is True
        assert event.result.output == "Done"


class TestAgentExecutionErrors:
    """Tests for agent execution error types."""

    def test_agent_execution_error(self) -> None:
        """Test AgentExecutionError."""
        error = AgentExecutionError(
            "Something went wrong",
            workspace_id="ws-123",
            execution_id="exec-456",
        )

        assert str(error) == "Something went wrong"
        assert error.workspace_id == "ws-123"
        assert error.execution_id == "exec-456"

    def test_agent_not_available_error(self) -> None:
        """Test AgentNotAvailableError."""
        error = AgentNotAvailableError(
            "API key not set",
            workspace_id="ws-123",
        )

        assert str(error) == "API key not set"
        assert isinstance(error, AgentExecutionError)

    def test_agent_budget_exceeded_error(self) -> None:
        """Test AgentBudgetExceededError."""
        error = AgentBudgetExceededError(
            "Budget exceeded",
            budget_usd=Decimal("1.00"),
            spent_usd=Decimal("1.50"),
        )

        assert str(error) == "Budget exceeded"
        assert error.budget_usd == Decimal("1.00")
        assert error.spent_usd == Decimal("1.50")


@pytest.mark.asyncio
class TestClaudeAgentExecutor:
    """Tests for ClaudeAgentExecutor."""

    async def test_executor_initialization(self) -> None:
        """Test executor can be initialized."""
        # Need to set APP_ENVIRONMENT=test to allow mock workspace
        with patch.dict(os.environ, {"APP_ENVIRONMENT": "test"}):
            from aef_adapters.agents.claude_executor import ClaudeAgentExecutor

            executor = ClaudeAgentExecutor()
            assert executor.provider_name == "claude"

    async def test_executor_factory(self) -> None:
        """Test get_claude_executor factory."""
        with patch.dict(os.environ, {"APP_ENVIRONMENT": "test"}):
            from aef_adapters.agents.claude_executor import (
                get_claude_executor,
                reset_claude_executor,
            )

            reset_claude_executor()  # Clear any cached instance

            executor1 = get_claude_executor()
            executor2 = get_claude_executor()

            # Should return same instance
            assert executor1 is executor2

            # With custom args, should return new instance
            executor3 = get_claude_executor(model="claude-sonnet")
            assert executor3 is not executor1

            reset_claude_executor()

    async def test_executor_fails_without_api_key(self) -> None:
        """Test executor fails when API key not set."""
        with patch.dict(
            os.environ,
            {"APP_ENVIRONMENT": "test", "ANTHROPIC_API_KEY": ""},
            clear=False,
        ):
            # Clear ANTHROPIC_API_KEY
            env = os.environ.copy()
            if "ANTHROPIC_API_KEY" in env:
                del env["ANTHROPIC_API_KEY"]

            with patch.dict(os.environ, env, clear=True):
                from aef_adapters.agents.claude_executor import ClaudeAgentExecutor

                executor = ClaudeAgentExecutor(api_key=None)

                # Create a mock workspace
                @dataclass
                class MockWorkspace:
                    isolation_id: str = "mock-ws"
                    workspace_path: Path = Path("/tmp/mock")

                @dataclass
                class MockConfig:
                    max_turns: int = 10
                    allowed_tools: frozenset[str] | None = None
                    permission_mode: str = "auto"
                    setting_sources: list[str] | None = None
                    max_budget_usd: float | None = None
                    timeout_seconds: int | None = None

                with pytest.raises(AgentNotAvailableError):
                    async for _ in executor.execute(
                        task="test",
                        workspace=MockWorkspace(),  # type: ignore[arg-type]
                        config=MockConfig(),  # type: ignore[arg-type]
                    ):
                        pass
