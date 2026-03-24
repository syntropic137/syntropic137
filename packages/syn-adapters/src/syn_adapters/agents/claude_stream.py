"""Claude streaming request logic.

Extracted from claude_helpers.py to reduce module complexity.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from syn_adapters.agents.protocol import (
    AgentAuthenticationError,
    AgentConfig,
    AgentError,
    AgentMessage,
    AgentProvider,
    AgentRateLimitError,
)
from syn_shared.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

logger = get_logger(__name__)


async def stream_request(
    client: Any,
    messages: list[AgentMessage],
    config: AgentConfig,
    default_model: str,
) -> AsyncIterator[str]:
    """Stream a response from Claude.

    Args:
        client: Anthropic async client instance.
        messages: Conversation history.
        config: Request configuration.
        default_model: Default model alias to use if config has none.

    Yields:
        Response content chunks.

    Raises:
        AgentError: If the request fails.
    """
    from syn_adapters.agents.claude_helpers import convert_messages, resolve_model

    raw_model = config.model or default_model
    model = resolve_model(raw_model)

    system_prompt, converted_messages = convert_messages(messages)

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
