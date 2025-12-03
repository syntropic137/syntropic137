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
    from aef_adapters.workspaces import LocalWorkspace, WorkspaceConfig

    agent = ClaudeAgenticAgent()

    async with LocalWorkspace.create(config) as workspace:
        async for event in agent.execute(
            task="Create a hello.py file",
            workspace=workspace,
            config=AgentExecutionConfig(max_turns=10),
        ):
            if isinstance(event, TaskCompleted):
                print(f"Done: {event.result}")

For Testing (Chat Completion - Legacy):
    from aef_adapters.agents import MockAgent, MockAgentConfig

    mock_config = MockAgentConfig(responses=["Test response"])
    agent = MockAgent(mock_config)

For Instrumented Agents (with observability):
    from aef_adapters.agents import InstrumentedAgent, SessionContext
    from aef_adapters.hooks import get_hook_client, ValidatorRegistry

    async with get_hook_client() as client:
        instrumented = InstrumentedAgent(
            agent=MockAgent(),
            hook_client=client,
            validators=ValidatorRegistry(),
        )
        instrumented.set_session_context("session-123")
        response = await instrumented.complete(messages, config)

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
from aef_adapters.agents.factory import (
    get_agent,
    get_available_agents,
    is_agent_available,
)
from aef_adapters.agents.instrumented import InstrumentedAgent
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

# Lazy imports for legacy adapters to avoid requiring their dependencies
# Use get_agent(AgentProvider.CLAUDE) or import directly when needed

__all__ = [
    # Agentic Protocol (recommended)
    "AgenticBudgetExceededError",
    "AgenticError",
    "AgenticProtocol",
    "AgenticSDKError",
    "AgenticTimeoutError",
    "AgenticTurnsExceededError",
    # Agentic Types
    "AgentEvent",
    "AgentExecutionConfig",
    "AgentExecutionResult",
    "AgentTool",
    "ClaudeAgenticAgent",
    "TaskCompleted",
    "TaskFailed",
    "TextOutput",
    "ThinkingUpdate",
    "ToolBlocked",
    "ToolUseCompleted",
    "ToolUseStarted",
    "Workspace",
    "WorkspaceConfig",
    # Chat Completion Protocol (legacy)
    "AgentAuthenticationError",
    "AgentConfig",
    "AgentError",
    "AgentMessage",
    "AgentMetrics",
    "AgentProtocol",
    "AgentProvider",
    "AgentRateLimitError",
    "AgentResponse",
    "AgentRole",
    "AgentTimeoutError",
    # Instrumented & Mock
    "InstrumentedAgent",
    "MockAgent",
    "MockAgentConfig",
    "MockAgentError",
    "SessionContext",
    # Factory
    "get_agent",
    "get_available_agents",
    "is_agent_available",
]
