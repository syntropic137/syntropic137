"""Claude agent configuration and model resolution helpers.

Extracted from claude.py to reduce module complexity.
Handles model alias resolution and auth mode determination.
"""

from __future__ import annotations

from syn_adapters.agents.protocol import AgentProvider
from syn_shared.logging import get_logger

logger = get_logger(__name__)


def resolve_model(model: str) -> str:
    """Resolve model alias to specific API version.

    Loads model definitions from agentic-primitives YAML files.

    Args:
        model: Model name or alias (e.g., "claude-sonnet", "sonnet")

    Returns:
        Specific API model name (e.g., "claude-sonnet-4-5-20250929")
    """
    from syn_adapters.agents.models import resolve_model as _resolve

    return _resolve(model)


def get_context_window(model: str) -> int:
    """Get context window size for a model.

    Args:
        model: Model name or alias

    Returns:
        Context window in tokens
    """
    from syn_adapters.agents.models import get_model_registry

    return get_model_registry().get_context_window(model)


def determine_auth_mode(
    oauth_token: str | None,
    api_key: str | None,
) -> str:
    """Determine authentication mode from available credentials.

    OAuth token takes priority over API key.

    Args:
        oauth_token: Claude Code OAuth token
        api_key: Anthropic API key

    Returns:
        Auth mode string: "oauth", "api_key", or "none"
    """
    if oauth_token:
        if api_key:
            logger.warning(
                "claude_auth_precedence",
                msg="Both CLAUDE_CODE_OAUTH_TOKEN and ANTHROPIC_API_KEY are set. "
                "Using CLAUDE_CODE_OAUTH_TOKEN. Remove ANTHROPIC_API_KEY to silence this warning.",
            )
        return "oauth"
    if api_key:
        return "api_key"
    return "none"


def get_anthropic_client(
    auth_mode: str,
    oauth_token: str | None,
    api_key: str | None,
) -> object:
    """Create an AsyncAnthropic client with the appropriate auth.

    Args:
        auth_mode: One of "oauth", "api_key"
        oauth_token: OAuth token (used if auth_mode is "oauth")
        api_key: API key (used if auth_mode is "api_key")

    Returns:
        AsyncAnthropic client instance

    Raises:
        AgentAuthenticationError: If no credentials configured
        AgentError: If anthropic package not installed
    """
    from syn_adapters.agents.protocol import AgentAuthenticationError, AgentError

    if not oauth_token and not api_key:
        msg = (
            "No Claude authentication configured. "
            "Set CLAUDE_CODE_OAUTH_TOKEN or ANTHROPIC_API_KEY."
        )
        raise AgentAuthenticationError(msg, AgentProvider.CLAUDE)

    try:
        from anthropic import AsyncAnthropic
    except ImportError as e:
        msg = "anthropic package not installed. Run: uv add anthropic"
        raise AgentError(msg, AgentProvider.CLAUDE) from e

    if auth_mode == "oauth":
        logger.info("claude_client_init", auth_mode="oauth")
        return AsyncAnthropic(auth_token=oauth_token)
    else:
        logger.info("claude_client_init", auth_mode="api_key")
        return AsyncAnthropic(api_key=api_key)
