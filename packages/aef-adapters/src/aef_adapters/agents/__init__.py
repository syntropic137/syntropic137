"""Agent adapters - integrations with AI providers.

This module provides adapters for AI agent providers (Claude, OpenAI).

## Chat Completion (Legacy)

    from aef_adapters.agents import get_agent, AgentMessage, AgentConfig

    agent = get_agent()
    response = await agent.complete(
        messages=[AgentMessage.user("Hello!")],
        config=AgentConfig(model="claude-sonnet-4-20250514"),
    )
    print(response.content)

## Agentic Execution (Recommended)

    from aef_adapters.agents import ClaudeAgenticAgent, AgentExecutionConfig
    from aef_adapters.workspace_backends.service import WorkspaceService

    agent = ClaudeAgenticAgent()
    service = WorkspaceService.create_docker()

    async with service.create_workspace(execution_id="exec-123") as workspace:
        # Workspace provides execute(), stream(), inject_files(), etc.
        result = await workspace.execute(["python", "script.py"])

For Testing (Chat Completion - Legacy):
    from aef_adapters.agents import MockAgent, MockAgentConfig

    mock_config = MockAgentConfig(responses=["Test response"])
    agent = MockAgent(mock_config)

For Testing (Agentic):
    Use unittest.mock to patch the claude-agent-sdk directly.
    See tests/test_claude_agentic.py for examples.

WARNING: MockAgent can ONLY be used when APP_ENVIRONMENT=test.
It will raise errors in development, staging, or production.
"""

from aef_adapters.agents.agentic_protocol import (
    AgenticBudgetExceededError,
    AgenticError,
    AgenticProtocol,
    AgenticSDKError,
    AgenticTimeoutError,
    AgenticTurnsExceededError,
)
from aef_adapters.agents.agentic_types import (
    AgentEvent,
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
from aef_adapters.agents.executor import (
    AgentBudgetExceededError,
    AgentExecutionError,
    AgentExecutionMetrics,
    AgentExecutor,
    AgentNotAvailableError,
    ExecutionCompleted,
    ExecutionEvent,
    ExecutionOutput,
    ExecutionProgress,
    ExecutionStarted,
    ExecutionToolUse,
    WorkspaceExecutionResult,
)
from aef_adapters.agents.factory import (
    get_agent,
    get_available_agents,
    is_agent_available,
)
from aef_adapters.agents.mock import MockAgent, MockAgentConfig, MockAgentError
from aef_adapters.agents.protocol import (
    AgentAuthenticationError,
    AgentConfig,
    AgentError,
    AgentMessage,
    AgentMetrics,
    AgentProtocol,
    AgentProvider,
    AgentRateLimitError,
    AgentResponse,
    AgentRole,
    AgentTimeoutError,
)
from aef_adapters.agents.session_context import SessionContext

# Agentic SDK adapters (require optional dependencies)
# These import conditionally to avoid ImportError if deps not installed
try:
    from aef_adapters.agents.claude_agentic import ClaudeAgenticAgent
except ImportError:
    ClaudeAgenticAgent = None  # type: ignore[assignment, misc]

# Agent executors (ADR-023)
try:
    from aef_adapters.agents.claude_executor import (
        ClaudeAgentExecutor,
        get_claude_executor,
        reset_claude_executor,
    )
except ImportError:
    ClaudeAgentExecutor = None  # type: ignore[assignment, misc]
    get_claude_executor = None  # type: ignore[assignment]
    reset_claude_executor = None  # type: ignore[assignment]

# Lazy imports for legacy adapters to avoid requiring their dependencies
# Use get_agent(AgentProvider.CLAUDE) or import directly when needed

__all__ = [
    # Chat Completion Protocol (legacy)
    "AgentAuthenticationError",
    # Agent Executor (ADR-023)
    "AgentBudgetExceededError",
    "AgentConfig",
    "AgentError",
    # Agentic Types
    "AgentEvent",
    "AgentExecutionConfig",
    "AgentExecutionError",
    "AgentExecutionMetrics",
    "AgentExecutionResult",
    "AgentExecutor",
    "AgentMessage",
    "AgentMetrics",
    "AgentNotAvailableError",
    "AgentProtocol",
    "AgentProvider",
    "AgentRateLimitError",
    "AgentResponse",
    "AgentRole",
    "AgentTimeoutError",
    "AgentTool",
    # Agentic Protocol (recommended)
    "AgenticBudgetExceededError",
    "AgenticError",
    "AgenticProtocol",
    "AgenticSDKError",
    "AgenticTimeoutError",
    "AgenticTurnsExceededError",
    "ClaudeAgentExecutor",
    "ClaudeAgenticAgent",
    "ExecutionCompleted",
    "ExecutionEvent",
    "ExecutionOutput",
    "ExecutionProgress",
    "ExecutionStarted",
    "ExecutionToolUse",
    # Mock agent
    "MockAgent",
    "MockAgentConfig",
    "MockAgentError",
    "SessionContext",
    "TaskCompleted",
    "TaskFailed",
    "TextOutput",
    "ThinkingUpdate",
    "ToolBlocked",
    "ToolUseCompleted",
    "ToolUseStarted",
    "Workspace",
    "WorkspaceConfig",
    "WorkspaceExecutionResult",
    # Factory
    "get_agent",
    "get_available_agents",
    "get_claude_executor",
    "is_agent_available",
    "reset_claude_executor",
]
