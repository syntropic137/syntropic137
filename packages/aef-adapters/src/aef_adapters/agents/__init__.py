"""Agent adapters - integrations with AI providers.

This module provides adapters for AI agent providers (Claude, OpenAI).

Quick Start:
    from aef_adapters.agents import get_agent, AgentMessage, AgentConfig

    # Auto-select available agent
    agent = get_agent()

    # Or specify provider
    from aef_adapters.agents import AgentProvider
    agent = get_agent(AgentProvider.CLAUDE)

    # Use the agent
    response = await agent.complete(
        messages=[AgentMessage.user("Hello!")],
        config=AgentConfig(model="claude-sonnet-4-20250514"),
    )
    print(response.content)

For Testing:
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
"""

from aef_adapters.agents.factory import (
    get_agent,
    get_available_agents,
    is_agent_available,
)
from aef_adapters.agents.instrumented import InstrumentedAgent
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
from aef_adapters.agents.session_context import SessionContext

# Lazy imports for adapters to avoid requiring their dependencies
# Use get_agent(AgentProvider.CLAUDE) or import directly when needed

__all__ = [
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
    "InstrumentedAgent",
    "MockAgent",
    "MockAgentConfig",
    "SessionContext",
    "get_agent",
    "get_available_agents",
    "is_agent_available",
]
