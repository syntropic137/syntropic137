"""Claude (Anthropic) agent adapter.

Integrates with Anthropic's Claude API for AI agent capabilities.
Requires the `anthropic` package and ANTHROPIC_API_KEY environment variable.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from aef_adapters.agents.protocol import (
    AgentAuthenticationError,
    AgentConfig,
    AgentError,
    AgentMessage,
    AgentProtocol,
    AgentProvider,
    AgentRateLimitError,
    AgentResponse,
    AgentRole,
    AgentTimeoutError,
)
from aef_shared import get_settings
from aef_shared.logging import get_logger

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
    DEFAULT_MODEL = "sonnet"

    @classmethod
    def resolve_model(cls, model: str) -> str:
        """Resolve model alias to specific API version.

        Loads model definitions from agentic-primitives YAML files.

        Args:
            model: Model name or alias (e.g., "claude-sonnet", "sonnet")

        Returns:
            Specific API model name (e.g., "claude-sonnet-4-5-20250929")
        """
        from aef_adapters.agents.models import resolve_model

        return resolve_model(model)

    @classmethod
    def get_context_window(cls, model: str) -> int:
        """Get context window size for a model.

        Args:
            model: Model name or alias

        Returns:
            Context window in tokens
        """
        from aef_adapters.agents.models import get_model_registry

        return get_model_registry().get_context_window(model)

    def __init__(self, api_key: str | None = None) -> None:
        """Initialize the Claude agent.

        Args:
            api_key: Anthropic API key. If not provided, reads from settings.
        """
        settings = get_settings()
        self._api_key = api_key or (
            settings.anthropic_api_key.get_secret_value() if settings.anthropic_api_key else None
        )
        self._client: Any | None = None

    @property
    def provider(self) -> AgentProvider:
        """Get the agent provider type."""
        return AgentProvider.CLAUDE

    @property
    def is_available(self) -> bool:
        """Check if the agent is configured and available."""
        return self._api_key is not None

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
        """
        if self._client is None:
            if not self._api_key:
                msg = "Anthropic API key not configured"
                raise AgentAuthenticationError(msg, AgentProvider.CLAUDE)

            try:
                from anthropic import AsyncAnthropic
            except ImportError as e:
                msg = "anthropic package not installed. Run: uv add anthropic"
                raise AgentError(msg, AgentProvider.CLAUDE) from e

            self._client = AsyncAnthropic(api_key=self._api_key)

        return self._client

    def _convert_messages(
        self, messages: list[AgentMessage]
    ) -> tuple[str | None, list[dict[str, str]]]:
        """Convert AgentMessages to Anthropic format.

        Returns:
            Tuple of (system_prompt, messages_list).
        """
        system_prompt: str | None = None
        converted: list[dict[str, str]] = []

        for msg in messages:
            if msg.role == AgentRole.SYSTEM:
                # Anthropic handles system as a separate parameter
                system_prompt = msg.content
            else:
                converted.append(
                    {
                        "role": msg.role.value,
                        "content": msg.content,
                    }
                )

        return system_prompt, converted

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
        client = self._get_client()
        raw_model = config.model or self.DEFAULT_MODEL
        model = self.resolve_model(raw_model)  # Resolve alias to API model name

        logger.debug(
            "model_resolved",
            raw_model=raw_model,
            resolved_model=model,
        )

        system_prompt, converted_messages = self._convert_messages(messages)

        # Use config system prompt if no system message in conversation
        if system_prompt is None and config.system_prompt:
            system_prompt = config.system_prompt

        logger.debug(
            "claude_request",
            model=model,
            message_count=len(converted_messages),
            max_tokens=config.max_tokens,
        )

        try:
            response = await asyncio.wait_for(
                client.messages.create(
                    model=model,
                    max_tokens=config.max_tokens,
                    temperature=config.temperature,
                    system=system_prompt or "",
                    messages=converted_messages,
                ),
                timeout=config.timeout_seconds,
            )

            content = response.content[0].text if response.content else ""
            result = AgentResponse(
                content=content,
                model=response.model,
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
                total_tokens=response.usage.input_tokens + response.usage.output_tokens,
                stop_reason=response.stop_reason,
            )

            logger.info(
                "claude_response",
                model=result.model,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                stop_reason=result.stop_reason,
            )

            return result

        except TimeoutError as e:
            msg = f"Claude request timed out after {config.timeout_seconds}s"
            logger.error("claude_timeout", timeout=config.timeout_seconds)
            raise AgentTimeoutError(msg, AgentProvider.CLAUDE) from e
        except Exception as e:
            error_msg = str(e)

            # Check for specific error types
            if "rate_limit" in error_msg.lower():
                logger.warning("claude_rate_limit", error=error_msg)
                raise AgentRateLimitError(error_msg, AgentProvider.CLAUDE) from e

            if "authentication" in error_msg.lower() or "api_key" in error_msg.lower():
                logger.error("claude_auth_error", error=error_msg)
                raise AgentAuthenticationError(error_msg, AgentProvider.CLAUDE) from e

            logger.error("claude_error", error=error_msg, error_type=type(e).__name__)
            raise AgentError(error_msg, AgentProvider.CLAUDE) from e

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
        client = self._get_client()
        raw_model = config.model or self.DEFAULT_MODEL
        model = self.resolve_model(raw_model)  # Resolve alias to specific version

        system_prompt, converted_messages = self._convert_messages(messages)

        if system_prompt is None and config.system_prompt:
            system_prompt = config.system_prompt

        logger.debug(
            "claude_stream_request",
            model=model,
            message_count=len(converted_messages),
        )

        try:
            async with client.messages.stream(
                model=model,
                max_tokens=config.max_tokens,
                temperature=config.temperature,
                system=system_prompt or "",
                messages=converted_messages,
            ) as stream:
                async for text in stream.text_stream:
                    yield text

        except Exception as e:
            error_msg = str(e)
            logger.error("claude_stream_error", error=error_msg)

            if "rate_limit" in error_msg.lower():
                raise AgentRateLimitError(error_msg, AgentProvider.CLAUDE) from e
            if "authentication" in error_msg.lower():
                raise AgentAuthenticationError(error_msg, AgentProvider.CLAUDE) from e

            raise AgentError(error_msg, AgentProvider.CLAUDE) from e
