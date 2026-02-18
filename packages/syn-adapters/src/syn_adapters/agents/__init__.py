"""Agent adapters - integrations with AI providers.

This module provides adapters for AI agent providers (Claude, OpenAI).

## Chat Completion

    from syn_adapters.agents import get_agent, AgentMessage, AgentConfig

    agent = get_agent()
    response = await agent.complete(
        messages=[AgentMessage.user("Hello!")],
        config=AgentConfig(model="claude-sonnet-4-20250514"),
    )
    print(response.content)

## Container Execution

    Use WorkspaceService directly with agentic_isolation for container execution.
    See WorkflowExecutionEngine for the primary workflow orchestration.

For Testing:
    from syn_adapters.agents import MockAgent, MockAgentConfig

    mock_config = MockAgentConfig(responses=["Test response"])
    agent = MockAgent(mock_config)

WARNING: MockAgent can ONLY be used when APP_ENVIRONMENT=test.
It will raise errors in development, staging, or production.
"""

from syn_adapters.agents.factory import (
    get_agent,
    get_available_agents,
    is_agent_available,
)
from syn_adapters.agents.mock import MockAgent, MockAgentConfig, MockAgentError
from syn_adapters.agents.protocol import (
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
from syn_adapters.agents.session_context import SessionContext

__all__ = [
    # Chat Completion Protocol
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
    # Mock agent
    "MockAgent",
    "MockAgentConfig",
    "MockAgentError",
    # Context
    "SessionContext",
    # Factory
    "get_agent",
    "get_available_agents",
    "is_agent_available",
]
