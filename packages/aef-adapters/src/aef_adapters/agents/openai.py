"""OpenAI agent adapter.

Integrates with OpenAI's API for AI agent capabilities.
Requires the `openai` package and OPENAI_API_KEY environment variable.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, ClassVar

from aef_adapters.agents.protocol import (
    AgentAuthenticationError,
    AgentConfig,
    AgentError,
    AgentMessage,
    AgentProtocol,
    AgentProvider,
    AgentRateLimitError,
    AgentResponse,
    AgentTimeoutError,
)
from aef_shared import get_settings
from aef_shared.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

logger = get_logger(__name__)


class OpenAIAgent(AgentProtocol):
    """OpenAI agent adapter using OpenAI's API.

    Usage:
        agent = OpenAIAgent()
        if agent.is_available:
            response = await agent.complete(
                messages=[AgentMessage.user("Hello!")],
                config=AgentConfig(model="gpt-4o"),
            )
    """

    # Default model - GPT-4o (latest as of 2025)
    DEFAULT_MODEL = "gpt-4o"

    # Supported models with context windows
    SUPPORTED_MODELS: ClassVar[dict[str, int]] = {
        "gpt-4o": 128_000,
        "gpt-4o-mini": 128_000,
        "gpt-4-turbo": 128_000,
        "gpt-4": 8_192,
        "gpt-3.5-turbo": 16_385,
        "o1": 200_000,
        "o1-mini": 128_000,
        "o1-preview": 128_000,
    }

    def __init__(self, api_key: str | None = None) -> None:
        """Initialize the OpenAI agent.

        Args:
            api_key: OpenAI API key. If not provided, reads from settings.
        """
        settings = get_settings()
        self._api_key = api_key or (
            settings.openai_api_key.get_secret_value() if settings.openai_api_key else None
        )
        self._client: Any | None = None

    @property
    def provider(self) -> AgentProvider:
        """Get the agent provider type."""
        return AgentProvider.OPENAI

    @property
    def is_available(self) -> bool:
        """Check if the agent is configured and available."""
        return self._api_key is not None

    def _get_client(self) -> Any:
        """Get or create the OpenAI client.

        Lazy initialization to avoid import errors when openai isn't installed.
        """
        if self._client is None:
            if not self._api_key:
                msg = "OpenAI API key not configured"
                raise AgentAuthenticationError(msg, AgentProvider.OPENAI)

            try:
                from openai import AsyncOpenAI
            except ImportError as e:
                msg = "openai package not installed. Run: uv add openai"
                raise AgentError(msg, AgentProvider.OPENAI) from e

            self._client = AsyncOpenAI(api_key=self._api_key)

        return self._client

    def _convert_messages(
        self, messages: list[AgentMessage], config: AgentConfig
    ) -> list[dict[str, str]]:
        """Convert AgentMessages to OpenAI format.

        Returns:
            List of message dicts with role and content.
        """
        converted: list[dict[str, str]] = []

        # Add system prompt first if provided in config
        if config.system_prompt:
            converted.append(
                {
                    "role": "system",
                    "content": config.system_prompt,
                }
            )

        for msg in messages:
            # OpenAI uses "system" directly in messages array
            converted.append(
                {
                    "role": msg.role.value,
                    "content": msg.content,
                }
            )

        return converted

    async def complete(
        self,
        messages: list[AgentMessage],
        config: AgentConfig,
    ) -> AgentResponse:
        """Send messages to OpenAI and get a response.

        Args:
            messages: Conversation history.
            config: Request configuration.

        Returns:
            Agent response with content and metrics.

        Raises:
            AgentError: If the request fails.
        """
        client = self._get_client()
        model = config.model or self.DEFAULT_MODEL

        if model not in self.SUPPORTED_MODELS:
            logger.warning(
                "unknown_openai_model",
                model=model,
                supported=list(self.SUPPORTED_MODELS.keys()),
            )

        converted_messages = self._convert_messages(messages, config)

        logger.debug(
            "openai_request",
            model=model,
            message_count=len(converted_messages),
            max_tokens=config.max_tokens,
        )

        # Build request kwargs - o1 models don't support temperature
        request_kwargs: dict[str, Any] = {
            "model": model,
            "messages": converted_messages,
            "max_completion_tokens": config.max_tokens,
        }

        # o1 models don't support temperature
        if not model.startswith("o1"):
            request_kwargs["temperature"] = config.temperature

        try:
            response = await asyncio.wait_for(
                client.chat.completions.create(**request_kwargs),
                timeout=config.timeout_seconds,
            )

            choice = response.choices[0] if response.choices else None
            content = choice.message.content if choice else ""
            stop_reason = choice.finish_reason if choice else None

            # OpenAI usage can be None for some responses
            usage = response.usage
            input_tokens = usage.prompt_tokens if usage else 0
            output_tokens = usage.completion_tokens if usage else 0

            result = AgentResponse(
                content=content or "",
                model=response.model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=input_tokens + output_tokens,
                stop_reason=stop_reason,
            )

            logger.info(
                "openai_response",
                model=result.model,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                stop_reason=result.stop_reason,
            )

            return result

        except TimeoutError as e:
            msg = f"OpenAI request timed out after {config.timeout_seconds}s"
            logger.error("openai_timeout", timeout=config.timeout_seconds)
            raise AgentTimeoutError(msg, AgentProvider.OPENAI) from e
        except Exception as e:
            error_msg = str(e)

            # Check for specific error types
            if "rate_limit" in error_msg.lower() or "429" in error_msg:
                logger.warning("openai_rate_limit", error=error_msg)
                raise AgentRateLimitError(error_msg, AgentProvider.OPENAI) from e

            if "authentication" in error_msg.lower() or "401" in error_msg:
                logger.error("openai_auth_error", error=error_msg)
                raise AgentAuthenticationError(error_msg, AgentProvider.OPENAI) from e

            logger.error("openai_error", error=error_msg, error_type=type(e).__name__)
            raise AgentError(error_msg, AgentProvider.OPENAI) from e

    async def stream(
        self,
        messages: list[AgentMessage],
        config: AgentConfig,
    ) -> AsyncIterator[str]:
        """Stream a response from OpenAI.

        Args:
            messages: Conversation history.
            config: Request configuration.

        Yields:
            Response content chunks.

        Raises:
            AgentError: If the request fails.
        """
        client = self._get_client()
        model = config.model or self.DEFAULT_MODEL

        converted_messages = self._convert_messages(messages, config)

        logger.debug(
            "openai_stream_request",
            model=model,
            message_count=len(converted_messages),
        )

        # Build request kwargs
        request_kwargs: dict[str, Any] = {
            "model": model,
            "messages": converted_messages,
            "max_completion_tokens": config.max_tokens,
            "stream": True,
        }

        if not model.startswith("o1"):
            request_kwargs["temperature"] = config.temperature

        try:
            stream = await client.chat.completions.create(**request_kwargs)

            async for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content

        except Exception as e:
            error_msg = str(e)
            logger.error("openai_stream_error", error=error_msg)

            if "rate_limit" in error_msg.lower() or "429" in error_msg:
                raise AgentRateLimitError(error_msg, AgentProvider.OPENAI) from e
            if "authentication" in error_msg.lower() or "401" in error_msg:
                raise AgentAuthenticationError(error_msg, AgentProvider.OPENAI) from e

            raise AgentError(error_msg, AgentProvider.OPENAI) from e
