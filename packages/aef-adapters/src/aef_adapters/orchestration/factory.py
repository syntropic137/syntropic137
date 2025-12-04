"""Factory for creating agentic agents.

Provides a factory pattern for instantiating agents that implement
the AgenticProtocol based on provider configuration.

Example:
    from aef_adapters.orchestration import get_agentic_agent

    # Get Claude agentic agent
    agent = get_agentic_agent("claude")

    # Check availability
    if agent.is_available:
        async for event in agent.execute(task, workspace, config):
            process(event)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from contextlib import AbstractAsyncContextManager as AsyncContextManager

    from aef_adapters.agents.agentic_protocol import AgenticProtocol
    from aef_adapters.agents.agentic_types import Workspace, WorkspaceConfig

logger = logging.getLogger(__name__)


class AgenticAgentFactory(Protocol):
    """Protocol for agentic agent factory functions."""

    def __call__(self, provider: str) -> AgenticProtocol:
        """Create an agentic agent for the given provider."""
        ...


def get_agentic_agent(provider: str) -> AgenticProtocol:
    """Get an agentic agent for the specified provider.

    Args:
        provider: Provider name (e.g., "claude", "openai").

    Returns:
        An AgenticProtocol implementation for the provider.

    Raises:
        ValueError: If the provider is not supported.
        RuntimeError: If the agent is not available (missing API key, etc.).

    Example:
        agent = get_agentic_agent("claude")
        if agent.is_available:
            async for event in agent.execute(task, workspace, config):
                handle_event(event)
    """

    # Normalize provider name
    provider_lower = provider.lower()

    if provider_lower in ("claude", "anthropic"):
        from aef_adapters.agents.claude_agentic import ClaudeAgenticAgent

        agent = ClaudeAgenticAgent()
        if not agent.is_available:
            logger.warning(
                "ClaudeAgenticAgent is not available. "
                "Check ANTHROPIC_API_KEY and claude-agent-sdk installation."
            )
        return agent

    # TODO: Add more providers (OpenAI, etc.) as they become available

    supported = ["claude", "anthropic"]
    raise ValueError(f"Unsupported agentic provider: {provider}. Supported providers: {supported}")


def get_available_agentic_agents() -> list[str]:
    """Get list of available agentic agent providers.

    Returns:
        List of provider names that have available agents.
    """
    available = []

    # Check Claude
    try:
        from aef_adapters.agents.claude_agentic import ClaudeAgenticAgent

        agent = ClaudeAgenticAgent()
        if agent.is_available:
            available.append("claude")
    except ImportError:
        # ClaudeAgenticAgent not available (missing dependency or API key)
        pass

    return available


# =============================================================================
# Workspace Factory
# =============================================================================


class WorkspaceFactory(Protocol):
    """Protocol for workspace factory functions."""

    def __call__(self, config: WorkspaceConfig) -> AsyncContextManager[Workspace]:
        """Create a workspace for the given configuration."""
        ...


def get_workspace(config: WorkspaceConfig) -> AsyncContextManager[Workspace]:
    """Get a workspace for agent execution.

    Currently returns a LocalWorkspace. Future versions may support
    Docker or cloud-based workspaces based on configuration.

    Args:
        config: Workspace configuration (session_id, paths, etc.)

    Returns:
        An async context manager that yields a configured Workspace.

    Example:
        async with get_workspace(config) as workspace:
            async for event in agent.execute(task, workspace, exec_config):
                handle_event(event)
    """
    from aef_adapters.workspaces import LocalWorkspace

    return LocalWorkspace.create(config)
