"""Claude (Anthropic) agent adapter.

Integrates with Anthropic's Claude API for AI agent capabilities.
Requires the `anthropic` package and either CLAUDE_CODE_OAUTH_TOKEN or
ANTHROPIC_API_KEY environment variable. OAuth token takes priority when both are set.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from syn_adapters.agents.claude_config import (
    determine_auth_mode,
    get_anthropic_client,
    get_context_window,
    resolve_model,
)
from syn_adapters.agents.protocol import (
    AgentConfig,
    AgentMessage,
    AgentProtocol,
    AgentProvider,
    AgentResponse,
)
from syn_shared import get_settings
from syn_shared.env_constants import MODEL_SONNET
from syn_shared.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

logger = get_logger(__name__)


class ClaudeAgent(AgentProtocol):
    """Claude agent adapter using Anthropic's API.

    Usage:
        agent = ClaudeAgent()
        if agent.is_available:
            response = await agent.complete(
                messages=[AgentMessage.user("Hello!")],
                config=AgentConfig(model="claude-sonnet"),  # Uses alias
            )

    Model Aliases:
        Use aliases for easier upgrades when new model versions are released.
        Aliases are loaded from agentic-primitives/providers/models/anthropic/.

        Common aliases:
        - "sonnet" or "claude-sonnet" -> latest Claude Sonnet
        - "opus" or "claude-opus" -> latest Claude Opus
        - "haiku" or "claude-haiku" -> latest Claude Haiku

        You can also use specific version names if needed.
    """

    # Default model alias - resolved from primitives
    # Use "sonnet" alias which maps to latest Claude Sonnet
    DEFAULT_MODEL = MODEL_SONNET

    @staticmethod
    def resolve_model(model: str) -> str:
        """Resolve model alias to specific API version.

        Loads model definitions from agentic-primitives YAML files.

        Args:
            model: Model name or alias (e.g., "claude-sonnet", "sonnet")

        Returns:
            Specific API model name (e.g., "claude-sonnet-4-5-20250929")
        """
        return resolve_model(model)

    @staticmethod
    def get_context_window(model: str) -> int:
        """Get context window size for a model.

        Args:
            model: Model name or alias

        Returns:
            Context window in tokens
        """
        return get_context_window(model)

    def __init__(
        self,
        api_key: str | None = None,
        oauth_token: str | None = None,
    ) -> None:
        """Initialize the Claude agent.

        Args:
            api_key: Anthropic API key. If not provided, reads from settings.
            oauth_token: Claude Code OAuth token. Takes priority over api_key.
        """
        settings = get_settings()

        # Resolve OAuth token: explicit arg > env var
        self._oauth_token = oauth_token or (
            settings.claude_code_oauth_token.get_secret_value()
            if settings.claude_code_oauth_token
            else None
        )

        # Resolve API key: explicit arg > env var
        self._api_key = api_key or (
            settings.anthropic_api_key.get_secret_value() if settings.anthropic_api_key else None
        )

        self._auth_mode: str = determine_auth_mode(self._oauth_token, self._api_key)
        self._client: Any | None = None

    @property
    def provider(self) -> AgentProvider:
        """Get the agent provider type."""
        return AgentProvider.CLAUDE

    @property
    def is_available(self) -> bool:
        """Check if the agent is configured and available."""
        return self._oauth_token is not None or self._api_key is not None

    def set_session_context(
        self,
        *,
        session_id: str,
        workflow_id: str,
        phase_id: str,
    ) -> None:
        """Set session context for observability correlation.

        Currently stored but not used - future integration with
        Anthropic's metadata headers for request correlation.
        """
        self._session_id = session_id
        self._workflow_id = workflow_id
        self._phase_id = phase_id

    def _get_client(self) -> Any:
        """Get or create the Anthropic client.

        Lazy initialization to avoid import errors when anthropic isn't installed.
        Uses OAuth token (auth_token) when available, otherwise falls back to API key.
        """
        if self._client is None:
            self._client = get_anthropic_client(
                self._auth_mode, self._oauth_token, self._api_key,
            )
        return self._client

    def _convert_messages(
        self, messages: list[AgentMessage]
    ) -> tuple[str | None, list[dict[str, str]]]:
        """Convert AgentMessages to Anthropic format.

        Returns:
            Tuple of (system_prompt, messages_list).
        """
        from syn_adapters.agents.claude_helpers import convert_messages

        return convert_messages(messages)

    async def complete(
        self,
        messages: list[AgentMessage],
        config: AgentConfig,
    ) -> AgentResponse:
        """Send messages to Claude and get a response.

        Args:
            messages: Conversation history.
            config: Request configuration.

        Returns:
            Agent response with content and metrics.

        Raises:
            AgentError: If the request fails.
        """
        from syn_adapters.agents.claude_helpers import complete_request

        return await complete_request(self._get_client(), messages, config, self.DEFAULT_MODEL)

    async def stream(
        self,
        messages: list[AgentMessage],
        config: AgentConfig,
    ) -> AsyncIterator[str]:
        """Stream a response from Claude.

        Args:
            messages: Conversation history.
            config: Request configuration.

        Yields:
            Response content chunks.

        Raises:
            AgentError: If the request fails.
        """
        from syn_adapters.agents.claude_helpers import stream_request

        async for chunk in stream_request(self._get_client(), messages, config, self.DEFAULT_MODEL):
            yield chunk
