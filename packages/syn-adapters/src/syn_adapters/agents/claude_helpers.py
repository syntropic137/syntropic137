"""Claude agent helper functions.

Extracted from claude.py to reduce module complexity.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from syn_adapters.agents.protocol import (
    AgentAuthenticationError,
    AgentConfig,
    AgentError,
    AgentMessage,
    AgentProvider,
    AgentRateLimitError,
    AgentResponse,
    AgentRole,
    AgentTimeoutError,
)
from syn_shared.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

logger = get_logger(__name__)


def convert_messages(
    messages: list[AgentMessage],
) -> tuple[str | None, list[dict[str, str]]]:
    """Convert AgentMessages to Anthropic format."""
    system_prompt: str | None = None
    converted: list[dict[str, str]] = []
    for msg in messages:
        if msg.role == AgentRole.SYSTEM:
            system_prompt = msg.content
        else:
            converted.append({"role": msg.role.value, "content": msg.content})
    return system_prompt, converted


def resolve_model(model: str) -> str:
    """Resolve model alias to specific API version."""
    from syn_adapters.agents.models import resolve_model as _resolve

    return _resolve(model)


def get_context_window(model: str) -> int:
    """Get context window size for a model."""
    from syn_adapters.agents.models import get_model_registry

    return get_model_registry().get_context_window(model)


async def complete_request(
    client: Any,
    messages: list[AgentMessage],
    config: AgentConfig,
    default_model: str,
) -> AgentResponse:
    """Send messages to Claude and get a response.

    Args:
        client: Anthropic async client instance.
        messages: Conversation history.
        config: Request configuration.
        default_model: Default model alias to use if config has none.

    Returns:
        Agent response with content and metrics.

    Raises:
        AgentError: If the request fails.
    """
    raw_model = config.model or default_model
    model = resolve_model(raw_model)

    logger.debug(
        "model_resolved",
        raw_model=raw_model,
        resolved_model=model,
    )

    system_prompt, converted_messages = convert_messages(messages)

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

        if "rate_limit" in error_msg.lower():
            logger.warning("claude_rate_limit", error=error_msg)
            raise AgentRateLimitError(error_msg, AgentProvider.CLAUDE) from e

        if "authentication" in error_msg.lower() or "api_key" in error_msg.lower():
            logger.error("claude_auth_error", error=error_msg)
            raise AgentAuthenticationError(error_msg, AgentProvider.CLAUDE) from e

        logger.error("claude_error", error=error_msg, error_type=type(e).__name__)
        raise AgentError(error_msg, AgentProvider.CLAUDE) from e


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
