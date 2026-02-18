"""Port interface for agent creation.

This port defines the contract for creating instrumented agents that can
execute tasks and emit observability events.
"""

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from syn_adapters.agents.protocol import AgentProtocol


class AgentFactoryPort(Protocol):
    """Port for creating instrumented agents.

    The agent factory creates agents with:
    - Proper instrumentation for observability
    - Session context (execution_id, phase_id, workflow_id)
    - Provider-specific configuration (Claude, OpenAI, etc.)

    Note: This is currently implemented as a simple callable (function),
    but defining it as a Protocol provides clarity and type safety.
    """

    def __call__(self, provider: str) -> "AgentProtocol":
        """Create an instrumented agent for the given provider.

        Args:
            provider: The agent provider identifier (e.g., "claude", "openai").

        Returns:
            Instrumented agent that can execute tasks and emit events.

        Raises:
            ValueError: If provider is unknown or not supported.

        Example:
            agent = agent_factory("claude")
            agent.set_session_context(
                session_id="session-123",
                workflow_id="workflow-456",
                phase_id="phase-789",
            )
            response = await agent.complete(messages, config)
        """
        ...
