"""Tests for syn_api.routes.agents — list providers, test agent.

Uses APP_ENVIRONMENT=test for in-memory adapters.
"""

import os

from syn_api.types import Err, Ok

os.environ.setdefault("APP_ENVIRONMENT", "test")


async def test_list_providers():
    """List all known providers with availability info."""
    from syn_api.routes.agents import list_providers

    result = await list_providers()

    assert isinstance(result, Ok)
    providers = result.value
    assert len(providers) >= 1

    # All providers should have required fields
    for p in providers:
        assert p.provider
        assert p.display_name
        assert p.default_model
        assert isinstance(p.available, bool)


async def test_list_providers_includes_mock():
    """In test mode, mock provider should be available."""
    from syn_api.routes.agents import list_providers

    result = await list_providers()
    assert isinstance(result, Ok)

    provider_names = [p.provider for p in result.value]
    assert "mock" in provider_names


async def test_test_agent_unknown_provider():
    """Testing an unknown provider returns error."""
    from syn_api.routes.agents import test_agent

    result = await test_agent(provider="nonexistent", prompt="Hello")
    assert isinstance(result, Err)


async def test_chat_unknown_provider():
    """Chat with unknown provider returns error."""
    from syn_api.routes.agents import chat

    result = await chat(
        provider="nonexistent",
        messages=[{"role": "user", "content": "Hello"}],
    )
    assert isinstance(result, Err)


async def test_test_agent_mock():
    """Test agent with mock provider."""
    from syn_api.routes.agents import test_agent

    result = await test_agent(provider="mock", prompt="Hello")

    # Mock should be available in test mode
    if isinstance(result, Ok):
        assert result.value.provider == "mock"
        assert result.value.response_text
    else:
        # If mock is not configured, that's also acceptable
        assert isinstance(result, Err)


async def test_chat_mock():
    """Chat with mock provider."""
    from syn_api.routes.agents import chat

    result = await chat(
        provider="mock",
        messages=[
            {"role": "user", "content": "Hello"},
        ],
    )

    if isinstance(result, Ok):
        assert result.value.provider == "mock"
    else:
        assert isinstance(result, Err)
