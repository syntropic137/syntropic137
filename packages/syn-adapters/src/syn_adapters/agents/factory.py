"""Agent factory for dependency injection.

Provides factory functions to create agent instances based on configuration.
Supports automatic selection of available agents.
"""

from __future__ import annotations

from pydantic import SecretStr

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
    with preference: Claude > Mock (test only).

    Args:
        provider: Specific provider to use, or None for auto-select.

    Returns:
        An agent instance implementing AgentProtocol.

    Raises:
        AgentError: If no agent is available or configured.
    """
    if provider == AgentProvider.MOCK:
        return _create_mock()

    if provider == AgentProvider.CLAUDE:
        return _create_claude_or_raise()

    if provider is None:
        return _auto_select()

    msg = f"Unknown agent provider: {provider}"
    raise AgentError(msg, AgentProvider.MOCK)


def _has_secret(val: SecretStr | None) -> bool:
    """Check if a SecretStr has a non-empty value."""
    return val is not None and bool(val.get_secret_value())


def _create_mock() -> AgentProtocol:
    """Create a mock agent instance."""
    from syn_adapters.agents.mock import MockAgent

    return MockAgent()


def _create_claude_or_raise() -> AgentProtocol:
    """Create a Claude agent, raising if unavailable."""
    from syn_adapters.agents.claude import ClaudeAgent

    claude = ClaudeAgent()
    if not claude.is_available:
        msg = (
            "Claude agent not available. "
            "Set CLAUDE_CODE_OAUTH_TOKEN or ANTHROPIC_API_KEY in environment."
        )
        raise AgentError(msg, AgentProvider.CLAUDE)
    return claude


def _auto_select() -> AgentProtocol:
    """Auto-select the best available agent provider."""
    settings = get_settings()

    if _has_secret(settings.claude_code_oauth_token) or _has_secret(settings.anthropic_api_key):
        from syn_adapters.agents.claude import ClaudeAgent

        claude_agent = ClaudeAgent()
        if claude_agent.is_available:
            logger.debug("auto_selected_agent", provider="claude")
            return claude_agent

    if settings.is_test:
        logger.debug("auto_selected_agent", provider="mock", reason="test_mode")
        return _create_mock()

    msg = (
        "No agent provider configured. Set one of: "
        "CLAUDE_CODE_OAUTH_TOKEN (Claude OAuth), ANTHROPIC_API_KEY (Claude)"
    )
    raise AgentError(msg, AgentProvider.MOCK)


def get_available_agents() -> list[AgentProvider]:
    """Get list of available agent providers.

    Returns:
        List of providers that are configured and ready to use.
    """
    settings = get_settings()
    available: list[AgentProvider] = []

    if _has_secret(settings.claude_code_oauth_token) or _has_secret(settings.anthropic_api_key):
        available.append(AgentProvider.CLAUDE)

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
