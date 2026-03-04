"""Agent operations — list providers, test, and chat.

Maps directly to syn_adapters.agents (no domain layer).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syn_api.types import (
    AgentError,
    AgentProviderInfo,
    AgentTestResult,
    Err,
    Ok,
    Result,
)

if TYPE_CHECKING:
    from syn_api.auth import AuthContext

# Provider display names and default models
_PROVIDER_META: dict[str, tuple[str, str]] = {
    "claude": ("Claude (Anthropic)", "claude-sonnet-4-20250514"),
    "openai": ("OpenAI", "gpt-4o"),
    "mock": ("Mock (test only)", "mock-v1"),
}


async def list_providers(
    auth: AuthContext | None = None,  # noqa: ARG001
) -> Result[list[AgentProviderInfo], AgentError]:
    """List available agent providers and their status.

    Args:
        auth: Optional authentication context.

    Returns:
        Ok(list[AgentProviderInfo]) on success, Err(AgentError) on failure.
    """
    from syn_adapters.agents import AgentProvider, get_available_agents, is_agent_available

    try:
        get_available_agents()

        providers = []
        for member in AgentProvider:
            display_name, default_model = _PROVIDER_META.get(
                member.value, (member.value.title(), "unknown")
            )
            providers.append(
                AgentProviderInfo(
                    provider=member.value,
                    display_name=display_name,
                    available=is_agent_available(member),
                    default_model=default_model,
                )
            )
        return Ok(providers)
    except Exception as e:
        return Err(AgentError.PROVIDER_NOT_FOUND, message=str(e))


async def test_agent(
    provider: str,
    prompt: str,
    model: str | None = None,
    auth: AuthContext | None = None,  # noqa: ARG001
) -> Result[AgentTestResult, AgentError]:
    """Test an agent provider with a simple prompt.

    Args:
        provider: Provider name (e.g. "claude", "openai").
        prompt: Test prompt to send.
        model: Optional model override.
        auth: Optional authentication context.

    Returns:
        Ok(AgentTestResult) on success, Err(AgentError) on failure.
    """
    from syn_adapters.agents import (
        AgentAuthenticationError,
        AgentConfig,
        AgentMessage,
        AgentProvider,
        get_agent,
    )

    try:
        provider_enum = AgentProvider(provider.lower())
    except ValueError:
        return Err(
            AgentError.PROVIDER_NOT_FOUND,
            message=f"Unknown provider: {provider}",
        )

    _, default_model = _PROVIDER_META.get(provider.lower(), (provider, "unknown"))
    use_model = model or default_model

    try:
        agent = get_agent(provider_enum)
    except Exception:
        return Err(
            AgentError.API_KEY_MISSING,
            message=f"Provider '{provider}' is not available — check API key configuration",
        )

    try:
        response = await agent.complete(
            messages=[AgentMessage.user(prompt)],
            config=AgentConfig(model=use_model),
        )
    except AgentAuthenticationError:
        return Err(
            AgentError.API_KEY_MISSING,
            message=f"Authentication failed for provider '{provider}'",
        )
    except Exception as e:
        return Err(AgentError.COMPLETION_FAILED, message=str(e))

    return Ok(
        AgentTestResult(
            provider=provider,
            model=response.model,
            response_text=response.content,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
        )
    )


async def chat(
    provider: str,
    messages: list[dict[str, str]],
    model: str | None = None,
    auth: AuthContext | None = None,  # noqa: ARG001
) -> Result[AgentTestResult, AgentError]:
    """Send a stateless chat completion request.

    Args:
        provider: Provider name (e.g. "claude", "openai").
        messages: List of message dicts with "role" and "content" keys.
        model: Optional model override.
        auth: Optional authentication context.

    Returns:
        Ok(AgentTestResult) on success, Err(AgentError) on failure.
    """
    from syn_adapters.agents import (
        AgentAuthenticationError,
        AgentConfig,
        AgentMessage,
        AgentProvider,
        AgentRole,
        get_agent,
    )

    try:
        provider_enum = AgentProvider(provider.lower())
    except ValueError:
        return Err(
            AgentError.PROVIDER_NOT_FOUND,
            message=f"Unknown provider: {provider}",
        )

    _, default_model = _PROVIDER_META.get(provider.lower(), (provider, "unknown"))
    use_model = model or default_model

    try:
        agent = get_agent(provider_enum)
    except Exception:
        return Err(
            AgentError.API_KEY_MISSING,
            message=f"Provider '{provider}' is not available — check API key configuration",
        )

    role_map = {
        "user": AgentRole.USER,
        "assistant": AgentRole.ASSISTANT,
        "system": AgentRole.SYSTEM,
    }

    agent_messages = []
    for msg in messages:
        role = role_map.get(msg.get("role", "user"), AgentRole.USER)
        agent_messages.append(AgentMessage(role=role, content=msg.get("content", "")))

    try:
        response = await agent.complete(
            messages=agent_messages,
            config=AgentConfig(model=use_model),
        )
    except AgentAuthenticationError:
        return Err(
            AgentError.API_KEY_MISSING,
            message=f"Authentication failed for provider '{provider}'",
        )
    except Exception as e:
        return Err(AgentError.COMPLETION_FAILED, message=str(e))

    return Ok(
        AgentTestResult(
            provider=provider,
            model=response.model,
            response_text=response.content,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
        )
    )
