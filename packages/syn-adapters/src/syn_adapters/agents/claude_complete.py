"""Claude complete (non-streaming) request logic.

Extracted from claude_helpers.py to reduce module complexity.
"""

from __future__ import annotations

import asyncio
from typing import Any, NoReturn

from syn_adapters.agents.protocol import (
    AgentAuthenticationError,
    AgentConfig,
    AgentError,
    AgentMessage,
    AgentProvider,
    AgentRateLimitError,
    AgentResponse,
    AgentTimeoutError,
)
from syn_shared.logging import get_logger

logger = get_logger(__name__)


def _classify_and_raise(exc: Exception) -> NoReturn:
    """Classify an exception from Claude API and raise the appropriate AgentError subtype."""
    error_msg = str(exc)
    lower = error_msg.lower()

    if "rate_limit" in lower:
        logger.warning("claude_rate_limit", error=error_msg)
        raise AgentRateLimitError(error_msg, AgentProvider.CLAUDE) from exc

    if "authentication" in lower or "api_key" in lower:
        logger.error("claude_auth_error", error=error_msg)
        raise AgentAuthenticationError(error_msg, AgentProvider.CLAUDE) from exc

    logger.error("claude_error", error=error_msg, error_type=type(exc).__name__)
    raise AgentError(error_msg, AgentProvider.CLAUDE) from exc


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
    from syn_adapters.agents.claude_helpers import convert_messages, resolve_model

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
        _classify_and_raise(e)
