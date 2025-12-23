"""Agent adapters - integrations with AI providers.

This module provides adapters for AI agent providers (Claude, OpenAI).

## Chat Completion

    from aef_adapters.agents import get_agent, AgentMessage, AgentConfig

    agent = get_agent()
    response = await agent.complete(
        messages=[AgentMessage.user("Hello!")],
        config=AgentConfig(model="claude-sonnet-4-20250514"),
    )
    print(response.content)

## Container Execution (ADR-029)

    from aef_adapters.agents import get_container_runner
    from aef_adapters.workspace_backends.service import WorkspaceService

    runner = await get_container_runner()
    service = WorkspaceService.create()

    async with service.create_workspace(execution_id="exec-123") as workspace:
        async for event in runner.execute(
            task="Create hello.py",
            workspace=workspace,
            session_id="session-123",
        ):
            print(event)

For Testing:
    from aef_adapters.agents import MockAgent, MockAgentConfig

    mock_config = MockAgentConfig(responses=["Test response"])
    agent = MockAgent(mock_config)

WARNING: MockAgent can ONLY be used when APP_ENVIRONMENT=test.
It will raise errors in development, staging, or production.
"""

from aef_adapters.agents.container_runner import (
    ContainerAgentRunner,
    ContainerCompleted,
    ContainerEvent,
    ContainerExecutionConfig,
    ContainerExecutionResult,
    ContainerFailed,
    ContainerOutput,
    ContainerToolCompleted,
    ContainerToolStarted,
    ContainerTurnCompleted,
    get_container_runner,
    reset_container_runner,
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
    # Container Runner (ADR-029)
    "ContainerAgentRunner",
    "ContainerCompleted",
    "ContainerEvent",
    "ContainerExecutionConfig",
    "ContainerExecutionResult",
    "ContainerFailed",
    "ContainerOutput",
    "ContainerToolCompleted",
    "ContainerToolStarted",
    "ContainerTurnCompleted",
    # Mock agent
    "MockAgent",
    "MockAgentConfig",
    "MockAgentError",
    # Context
    "SessionContext",
    # Factory
    "get_agent",
    "get_available_agents",
    "get_container_runner",
    "is_agent_available",
    "reset_container_runner",
]
