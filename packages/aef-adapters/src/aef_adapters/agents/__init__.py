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

    from aef_adapters.agents import AgenticProtocol, AgentExecutionConfig

    # Agent executes task autonomously with tools
    async for event in agent.execute(
        task="Create a hello.py file",
        workspace=workspace,
        config=AgentExecutionConfig(max_turns=10),
    ):
        if isinstance(event, TaskCompleted):
            print(f"Done: {event.result}")

For Testing:
    from aef_adapters.agents import MockAgent, MockAgentConfig

    mock_config = MockAgentConfig(responses=["Test response"])
    agent = MockAgent(mock_config)
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
from aef_adapters.agents.mock import MockAgent, MockAgentConfig
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

# Lazy imports for adapters to avoid requiring their dependencies
# Use get_agent(AgentProvider.CLAUDE) or import directly when needed

__all__ = [
    # Agentic Protocol (recommended)
    "AgenticProtocol",
    "AgenticError",
    "AgenticBudgetExceededError",
    "AgenticTurnsExceededError",
    "AgenticTimeoutError",
    "AgenticSDKError",
    # Agentic Types
    "AgentExecutionConfig",
    "AgentExecutionResult",
    "AgentEvent",
    "AgentTool",
    "ToolUseStarted",
    "ToolUseCompleted",
    "ToolBlocked",
    "ThinkingUpdate",
    "TextOutput",
    "TaskCompleted",
    "TaskFailed",
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
    # Mock Agent
    "MockAgent",
    "MockAgentConfig",
    # Factory
    "get_agent",
    "get_available_agents",
    "is_agent_available",
]
