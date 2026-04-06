"""Agent API endpoints and service operations.

Provides agent provider listing, testing, and chat completion.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException

from syn_api.types import (
    AgentChatRequest,
    AgentError,
    AgentProviderInfo,
    AgentProviderListResponse,
    AgentTestRequest,
    AgentTestResult,
    Err,
    Ok,
    Result,
)

if TYPE_CHECKING:
    from syn_api.auth import AuthContext

router = APIRouter(prefix="/agents", tags=["agents"])

# Provider display names and default models
_PROVIDER_META: dict[str, tuple[str, str]] = {
    "claude": ("Claude (Anthropic)", "claude-sonnet-4-20250514"),
    "mock": ("Mock (test only)", "mock-v1"),
}


# =============================================================================
# Service functions (importable by tests)
# =============================================================================


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
        provider: Provider name (e.g. "claude").
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
        provider: Provider name (e.g. "claude").
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


# =============================================================================
# HTTP Endpoints
# =============================================================================


@router.get("/providers", response_model=AgentProviderListResponse)
async def list_providers_endpoint() -> AgentProviderListResponse:
    """List available agent providers."""
    result = await list_providers()

    if isinstance(result, Err):
        raise HTTPException(status_code=500, detail=result.message)

    return AgentProviderListResponse(
        providers=result.value,
        total=len(result.value),
    )


@router.post("/test")
async def test_agent_endpoint(body: AgentTestRequest) -> AgentTestResult:
    """Test an agent provider with a simple prompt."""
    result = await test_agent(
        provider=body.provider,
        prompt=body.prompt,
        model=body.model,
    )

    if isinstance(result, Err):
        status = 400 if result.error == AgentError.PROVIDER_NOT_FOUND else 502
        raise HTTPException(status_code=status, detail=result.message)

    return result.value


@router.post("/chat")
async def chat_endpoint(body: AgentChatRequest) -> AgentTestResult:
    """Send a stateless chat completion request."""
    result = await chat(
        provider=body.provider,
        messages=[{"role": m.role, "content": m.content} for m in body.messages],
        model=body.model,
    )

    if isinstance(result, Err):
        status = 400 if result.error == AgentError.PROVIDER_NOT_FOUND else 502
        raise HTTPException(status_code=status, detail=result.message)

    return result.value
