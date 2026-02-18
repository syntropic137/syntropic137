"""Agent factory for dependency injection.

Provides factory functions to create agent instances based on configuration.
Supports automatic selection of available agents.
"""

from __future__ import annotations

from syn_adapters.agents.protocol import (
    AgentError,
    AgentProtocol,
    AgentProvider,
)
from syn_shared import get_settings
from syn_shared.logging import get_logger

logger = get_logger(__name__)


def get_agent(provider: AgentProvider | None = None) -> AgentProtocol:
    """Get an agent instance.

    If no provider is specified, returns the first available agent
    with preference: Claude > OpenAI > Mock (test only).

    Args:
        provider: Specific provider to use, or None for auto-select.

    Returns:
        An agent instance implementing AgentProtocol.

    Raises:
        AgentError: If no agent is available or configured.
    """
    settings = get_settings()

    if provider == AgentProvider.MOCK:
        from syn_adapters.agents.mock import MockAgent

        return MockAgent()

    if provider == AgentProvider.CLAUDE:
        from syn_adapters.agents.claude import ClaudeAgent

        claude = ClaudeAgent()
        if not claude.is_available:
            msg = (
                "Claude agent not available. "
                "Set CLAUDE_CODE_OAUTH_TOKEN or ANTHROPIC_API_KEY in environment."
            )
            raise AgentError(msg, AgentProvider.CLAUDE)
        return claude

    if provider == AgentProvider.OPENAI:
        from syn_adapters.agents.openai import OpenAIAgent

        openai = OpenAIAgent()
        if not openai.is_available:
            msg = (
                "OpenAI agent not available. Set OPENAI_API_KEY in environment. "
                "Get key from: https://platform.openai.com/api-keys"
            )
            raise AgentError(msg, AgentProvider.OPENAI)
        return openai

    # Auto-select: try Claude first, then OpenAI
    if provider is None:
        # Check Claude (OAuth token or API key)
        if settings.claude_code_oauth_token or settings.anthropic_api_key:
            from syn_adapters.agents.claude import ClaudeAgent

            claude_agent = ClaudeAgent()
            if claude_agent.is_available:
                logger.debug("auto_selected_agent", provider="claude")
                return claude_agent

        # Check OpenAI
        if settings.openai_api_key:
            from syn_adapters.agents.openai import OpenAIAgent

            openai_agent = OpenAIAgent()
            if openai_agent.is_available:
                logger.debug("auto_selected_agent", provider="openai")
                return openai_agent

        # Use mock in test mode
        if settings.is_test:
            from syn_adapters.agents.mock import MockAgent

            logger.debug("auto_selected_agent", provider="mock", reason="test_mode")
            return MockAgent()

        msg = (
            "No agent provider configured. Set one of: "
            "CLAUDE_CODE_OAUTH_TOKEN (Claude OAuth), ANTHROPIC_API_KEY (Claude), OPENAI_API_KEY (OpenAI)"
        )
        raise AgentError(msg, AgentProvider.MOCK)

    msg = f"Unknown agent provider: {provider}"
    raise AgentError(msg, AgentProvider.MOCK)


def get_available_agents() -> list[AgentProvider]:
    """Get list of available agent providers.

    Returns:
        List of providers that are configured and ready to use.
    """
    settings = get_settings()
    available: list[AgentProvider] = []

    if settings.claude_code_oauth_token or settings.anthropic_api_key:
        available.append(AgentProvider.CLAUDE)

    if settings.openai_api_key:
        available.append(AgentProvider.OPENAI)

    # Mock is always available in test mode
    if settings.is_test:
        available.append(AgentProvider.MOCK)

    return available


def is_agent_available(provider: AgentProvider) -> bool:
    """Check if a specific agent provider is available.

    Args:
        provider: The provider to check.

    Returns:
        True if the provider is configured and ready.
    """
    return provider in get_available_agents()
