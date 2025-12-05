"""Tests for ClaudeAgenticAgent - the agentic SDK adapter.

These tests mock the claude-agent-sdk to test the agent's behavior
without requiring actual API calls or SDK installation.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path  # noqa: TC003
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from aef_adapters.agents.agentic_protocol import AgenticSDKError
from aef_adapters.agents.agentic_types import (
    AgentExecutionConfig,
    AgentTool,
    TaskCompleted,
    TaskFailed,
    TextOutput,
    ToolUseCompleted,
    ToolUseStarted,
    Workspace,
    WorkspaceConfig,
)
from aef_adapters.agents.protocol import AgentProvider

# ============================================================================
# Mock SDK Types
# ============================================================================


@dataclass
class MockTextBlock:
    """Mock TextBlock from claude-agent-sdk."""

    text: str


@dataclass
class MockToolUseBlock:
    """Mock ToolUseBlock from claude-agent-sdk."""

    name: str
    id: str
    input: dict[str, Any]


@dataclass
class MockAssistantMessage:
    """Mock AssistantMessage from claude-agent-sdk."""

    content: list[MockTextBlock | MockToolUseBlock]


@dataclass
class MockResultMessage:
    """Mock ResultMessage from claude-agent-sdk."""

    result: str
    usage: dict[str, int] | None = None


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def workspace(tmp_path: Path) -> Workspace:
    """Create a test workspace."""
    workspace_path = tmp_path / "test_workspace"
    workspace_path.mkdir(parents=True)

    config = WorkspaceConfig(
        session_id="test-session-123",
        base_dir=tmp_path,
    )

    return Workspace(path=workspace_path, config=config)


@pytest.fixture
def execution_config() -> AgentExecutionConfig:
    """Create a default execution config."""
    return AgentExecutionConfig(
        max_turns=5,
        max_budget_usd=1.0,
        timeout_seconds=60,
    )


# ============================================================================
# Test ClaudeAgenticAgent Creation
# ============================================================================


class TestClaudeAgenticAgentCreation:
    """Tests for ClaudeAgenticAgent initialization."""

    def test_create_with_defaults(self) -> None:
        """Test creating agent with default settings."""
        # Mock the SDK import
        with patch.dict(
            "aef_adapters.agents.claude_agentic.__dict__",
            {"CLAUDE_SDK_AVAILABLE": True},
        ):
            from aef_adapters.agents.claude_agentic import ClaudeAgenticAgent

            agent = ClaudeAgenticAgent()

            # NOTE: Default is Haiku for cost reduction during testing
            assert agent._model == "claude-3-5-haiku-20241022"
            assert agent.provider == AgentProvider.CLAUDE

    def test_create_with_custom_model(self) -> None:
        """Test creating agent with custom model."""
        with patch.dict(
            "aef_adapters.agents.claude_agentic.__dict__",
            {"CLAUDE_SDK_AVAILABLE": True},
        ):
            from aef_adapters.agents.claude_agentic import ClaudeAgenticAgent

            agent = ClaudeAgenticAgent(model="claude-3-5-haiku-20241022")

            assert agent._model == "claude-3-5-haiku-20241022"

    def test_supported_tools(self) -> None:
        """Test that supported tools are correctly defined."""
        with patch.dict(
            "aef_adapters.agents.claude_agentic.__dict__",
            {"CLAUDE_SDK_AVAILABLE": True},
        ):
            from aef_adapters.agents.claude_agentic import ClaudeAgenticAgent

            agent = ClaudeAgenticAgent()

            assert agent.supported_tools == frozenset(AgentTool.all())
            assert "Read" in agent.supported_tools
            assert "Write" in agent.supported_tools
            assert "Bash" in agent.supported_tools

    def test_is_available_without_api_key(self) -> None:
        """Test is_available returns False without API key."""
        with (
            patch.dict(
                "aef_adapters.agents.claude_agentic.__dict__",
                {"CLAUDE_SDK_AVAILABLE": True},
            ),
            patch.dict("os.environ", {}, clear=True),
        ):
            from aef_adapters.agents.claude_agentic import ClaudeAgenticAgent

            agent = ClaudeAgenticAgent(api_key=None)

            assert not agent.is_available

    def test_is_available_with_api_key(self) -> None:
        """Test is_available returns True with API key."""
        with patch.dict(
            "aef_adapters.agents.claude_agentic.__dict__",
            {"CLAUDE_SDK_AVAILABLE": True},
        ):
            from aef_adapters.agents.claude_agentic import ClaudeAgenticAgent

            agent = ClaudeAgenticAgent(api_key="test-key-123")

            assert agent.is_available


# ============================================================================
# Test Execute Method
# ============================================================================


class TestClaudeAgenticAgentExecute:
    """Tests for ClaudeAgenticAgent.execute() method."""

    @pytest.mark.asyncio
    async def test_execute_without_sdk_raises_error(
        self,
        workspace: Workspace,
        execution_config: AgentExecutionConfig,
    ) -> None:
        """Test that execute raises error when SDK not installed."""
        with patch.dict(
            "aef_adapters.agents.claude_agentic.__dict__",
            {"CLAUDE_SDK_AVAILABLE": False},
        ):
            from aef_adapters.agents.claude_agentic import ClaudeAgenticAgent

            agent = ClaudeAgenticAgent(api_key="test-key")

            with pytest.raises(AgenticSDKError) as exc_info:
                async for _ in agent.execute(
                    task="Test task",
                    workspace=workspace,
                    config=execution_config,
                ):
                    pass

            assert "claude-agent-sdk is not installed" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_execute_without_api_key_raises_error(
        self,
        workspace: Workspace,
        execution_config: AgentExecutionConfig,
    ) -> None:
        """Test that execute raises error when API key not set."""
        with (
            patch.dict(
                "aef_adapters.agents.claude_agentic.__dict__",
                {"CLAUDE_SDK_AVAILABLE": True},
            ),
            patch.dict("os.environ", {}, clear=True),
        ):
            from aef_adapters.agents.claude_agentic import ClaudeAgenticAgent

            agent = ClaudeAgenticAgent(api_key=None)

            with pytest.raises(AgenticSDKError) as exc_info:
                async for _ in agent.execute(
                    task="Test task",
                    workspace=workspace,
                    config=execution_config,
                ):
                    pass

            assert "ANTHROPIC_API_KEY" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_execute_simple_task_success(
        self,
        workspace: Workspace,
        execution_config: AgentExecutionConfig,
    ) -> None:
        """Test successful simple task execution."""
        # Create mock SDK messages
        mock_messages = [
            MockAssistantMessage(content=[MockTextBlock(text="Hello, I'll help you.")]),
            MockResultMessage(
                result="Task completed successfully.",
                usage={"input_tokens": 100, "output_tokens": 50},
            ),
        ]

        async def mock_query(*_args: Any, **_kwargs: Any):
            for msg in mock_messages:
                yield msg

        # Patch the SDK
        with (
            patch.dict(
                "aef_adapters.agents.claude_agentic.__dict__",
                {
                    "CLAUDE_SDK_AVAILABLE": True,
                    "query": mock_query,
                    "AssistantMessage": MockAssistantMessage,
                    "ResultMessage": MockResultMessage,
                    "ToolUseBlock": MockToolUseBlock,
                    "ClaudeAgentOptions": MagicMock,
                },
            ),
        ):
            from aef_adapters.agents.claude_agentic import ClaudeAgenticAgent

            agent = ClaudeAgenticAgent(api_key="test-key")

            events = []
            async for event in agent.execute(
                task="Say hello",
                workspace=workspace,
                config=execution_config,
            ):
                events.append(event)

            # Check we got text output and task completed
            assert len(events) >= 2

            # Check text output event
            text_events = [e for e in events if isinstance(e, TextOutput)]
            assert len(text_events) == 1
            assert text_events[0].content == "Hello, I'll help you."

            # Check task completed event
            completed_events = [e for e in events if isinstance(e, TaskCompleted)]
            assert len(completed_events) == 1
            completed = completed_events[0]
            assert completed.result == "Task completed successfully."
            assert completed.input_tokens == 100
            assert completed.output_tokens == 50
            assert completed.total_tokens == 150
            assert completed.turns_used == 1

    @pytest.mark.asyncio
    async def test_execute_with_tool_use(
        self,
        workspace: Workspace,
        execution_config: AgentExecutionConfig,
    ) -> None:
        """Test execution with tool calls."""
        # Create mock SDK messages with tool use
        mock_messages = [
            MockAssistantMessage(
                content=[
                    MockTextBlock(text="I'll create the file."),
                    MockToolUseBlock(
                        name="Write",
                        id="tool-use-123",
                        input={"path": "hello.py", "content": "print('Hello')"},
                    ),
                ]
            ),
            MockAssistantMessage(content=[MockTextBlock(text="File created.")]),
            MockResultMessage(
                result="Created hello.py successfully.",
                usage={"input_tokens": 200, "output_tokens": 100},
            ),
        ]

        async def mock_query(*_args: Any, **_kwargs: Any):
            for msg in mock_messages:
                yield msg

        with (
            patch.dict(
                "aef_adapters.agents.claude_agentic.__dict__",
                {
                    "CLAUDE_SDK_AVAILABLE": True,
                    "query": mock_query,
                    "AssistantMessage": MockAssistantMessage,
                    "ResultMessage": MockResultMessage,
                    "ToolUseBlock": MockToolUseBlock,
                    "ClaudeAgentOptions": MagicMock,
                },
            ),
        ):
            from aef_adapters.agents.claude_agentic import ClaudeAgenticAgent

            agent = ClaudeAgenticAgent(api_key="test-key")

            events = []
            async for event in agent.execute(
                task="Create hello.py",
                workspace=workspace,
                config=execution_config,
            ):
                events.append(event)

            # Check tool use events
            tool_started = [e for e in events if isinstance(e, ToolUseStarted)]
            assert len(tool_started) == 1
            assert tool_started[0].tool_name == "Write"
            assert tool_started[0].tool_use_id == "tool-use-123"
            assert tool_started[0].tool_input["path"] == "hello.py"

            tool_completed = [e for e in events if isinstance(e, ToolUseCompleted)]
            assert len(tool_completed) == 1
            assert tool_completed[0].tool_name == "Write"
            assert tool_completed[0].success is True

            # Check final result
            completed = [e for e in events if isinstance(e, TaskCompleted)]
            assert len(completed) == 1
            assert "Write" in completed[0].tools_used
            assert completed[0].turns_used == 2

    @pytest.mark.asyncio
    async def test_execute_handles_sdk_error(
        self,
        workspace: Workspace,
        execution_config: AgentExecutionConfig,
    ) -> None:
        """Test that SDK errors are caught and converted to TaskFailed."""

        async def mock_query_error(*_args: Any, **_kwargs: Any):
            yield MockAssistantMessage(content=[MockTextBlock(text="Starting...")])
            raise RuntimeError("SDK connection failed")

        with (
            patch.dict(
                "aef_adapters.agents.claude_agentic.__dict__",
                {
                    "CLAUDE_SDK_AVAILABLE": True,
                    "query": mock_query_error,
                    "AssistantMessage": MockAssistantMessage,
                    "ResultMessage": MockResultMessage,
                    "ToolUseBlock": MockToolUseBlock,
                    "ClaudeAgentOptions": MagicMock,
                },
            ),
        ):
            from aef_adapters.agents.claude_agentic import ClaudeAgenticAgent

            agent = ClaudeAgenticAgent(api_key="test-key")

            events = []
            async for event in agent.execute(
                task="Test task",
                workspace=workspace,
                config=execution_config,
            ):
                events.append(event)

            # Should have task failed event
            failed_events = [e for e in events if isinstance(e, TaskFailed)]
            assert len(failed_events) == 1
            failed = failed_events[0]
            assert "SDK connection failed" in failed.error
            assert failed.error_type == "sdk_error"


# ============================================================================
# Test Config Integration
# ============================================================================


class TestConfigIntegration:
    """Tests for configuration integration with ClaudeAgenticAgent."""

    @pytest.mark.asyncio
    async def test_config_tools_passed_to_sdk(
        self,
        workspace: Workspace,
    ) -> None:
        """Test that config tools are passed to SDK options."""
        captured_options: list[Any] = []

        mock_options_class = MagicMock()
        mock_options_class.side_effect = lambda **kwargs: (
            captured_options.append(kwargs) or MagicMock()
        )

        async def mock_query(*_args: Any, **_kwargs: Any):
            yield MockResultMessage(result="Done", usage={"input_tokens": 10, "output_tokens": 5})

        config = AgentExecutionConfig(
            allowed_tools=frozenset({"Read", "Write"}),
            max_turns=3,
            max_budget_usd=0.50,
            permission_mode="askForPermission",
        )

        with (
            patch.dict(
                "aef_adapters.agents.claude_agentic.__dict__",
                {
                    "CLAUDE_SDK_AVAILABLE": True,
                    "query": mock_query,
                    "AssistantMessage": MockAssistantMessage,
                    "ResultMessage": MockResultMessage,
                    "ToolUseBlock": MockToolUseBlock,
                    "ClaudeAgentOptions": mock_options_class,
                },
            ),
        ):
            from aef_adapters.agents.claude_agentic import ClaudeAgenticAgent

            agent = ClaudeAgenticAgent(api_key="test-key", model="claude-3-opus")

            events = []
            async for event in agent.execute(
                task="Test",
                workspace=workspace,
                config=config,
            ):
                events.append(event)

            # Verify options were passed
            assert len(captured_options) == 1
            opts = captured_options[0]

            # Check model
            assert opts["model"] == "claude-3-opus"

            # Check workspace path
            assert opts["cwd"] == str(workspace.path)

            # Check tools
            assert set(opts["allowed_tools"]) == {"Read", "Write"}

            # Check limits
            assert opts["max_turns"] == 3
            assert opts["max_budget_usd"] == 0.50

            # Check permission mode
            assert opts["permission_mode"] == "askForPermission"
