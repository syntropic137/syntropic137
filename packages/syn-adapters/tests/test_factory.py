"""Tests for agent factory."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from syn_adapters.agents import (
    AgentError,
    AgentProvider,
    get_agent,
    get_available_agents,
    is_agent_available,
)
from syn_adapters.agents.mock import MockAgent
from syn_shared.settings import reset_settings

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture(autouse=True)
def _reset_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Reset environment for each test.

    Uses a temporary directory to prevent loading from project .env file.
    """
    # Change to temp dir to avoid loading project .env
    monkeypatch.chdir(tmp_path)
    # Clear any existing API keys / tokens from env
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    monkeypatch.setenv("APP_ENVIRONMENT", "test")
    reset_settings()


@pytest.mark.unit
class TestGetAgent:
    """Tests for get_agent factory function."""

    def test_get_mock_agent(self) -> None:
        """Test getting mock agent explicitly."""
        agent = get_agent(AgentProvider.MOCK)
        assert isinstance(agent, MockAgent)
        assert agent.provider == AgentProvider.MOCK

    def test_get_claude_without_key_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test Claude agent raises without API key or OAuth token."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
        reset_settings()

        with pytest.raises(AgentError) as exc_info:
            get_agent(AgentProvider.CLAUDE)

        assert "CLAUDE_CODE_OAUTH_TOKEN" in str(exc_info.value)
        assert "ANTHROPIC_API_KEY" in str(exc_info.value)

    def test_auto_select_mock_in_test_mode(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test auto-selection falls back to mock in test mode."""
        monkeypatch.setenv("APP_ENVIRONMENT", "test")
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        reset_settings()

        agent = get_agent(None)
        assert isinstance(agent, MockAgent)

    def test_auto_select_prefers_claude(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test auto-selection prefers Claude when available."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        reset_settings()

        # This will use Claude adapter but won't actually call API
        # just tests the selection logic
        from syn_adapters.agents.claude import ClaudeAgent

        agent = get_agent(None)
        assert isinstance(agent, ClaudeAgent)

    def test_auto_select_claude_with_oauth_token(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test auto-selection picks Claude when OAuth token is set."""
        monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "oauth-test-token")
        reset_settings()

        from syn_adapters.agents.claude import ClaudeAgent

        agent = get_agent(None)
        assert isinstance(agent, ClaudeAgent)

    def test_get_claude_with_oauth_token(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test getting Claude agent with OAuth token explicitly."""
        monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "oauth-test-token")
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        reset_settings()

        from syn_adapters.agents.claude import ClaudeAgent

        agent = get_agent(AgentProvider.CLAUDE)
        assert isinstance(agent, ClaudeAgent)
        assert agent.is_available

class TestGetAvailableAgents:
    """Tests for get_available_agents function."""

    def test_includes_claude_when_configured(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test Claude included when API key set."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        reset_settings()

        available = get_available_agents()
        assert AgentProvider.CLAUDE in available

    def test_includes_claude_when_oauth_token_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test Claude included when OAuth token set."""
        monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "oauth-test-token")
        reset_settings()

        available = get_available_agents()
        assert AgentProvider.CLAUDE in available

    def test_includes_mock_in_test_mode(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test Mock included in test mode."""
        monkeypatch.setenv("APP_ENVIRONMENT", "test")
        reset_settings()

        available = get_available_agents()
        assert AgentProvider.MOCK in available

    def test_excludes_mock_in_production(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test Mock excluded in production mode."""
        monkeypatch.setenv("APP_ENVIRONMENT", "production")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test")  # Need at least one agent
        reset_settings()

        available = get_available_agents()
        assert AgentProvider.MOCK not in available


class TestIsAgentAvailable:
    """Tests for is_agent_available function."""

    def test_claude_available_with_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test Claude availability with key."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        reset_settings()

        assert is_agent_available(AgentProvider.CLAUDE) is True

    def test_claude_available_with_oauth_token(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test Claude availability with OAuth token."""
        monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "oauth-test-token")
        reset_settings()

        assert is_agent_available(AgentProvider.CLAUDE) is True

    def test_claude_unavailable_without_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test Claude unavailability without key or OAuth token."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
        reset_settings()

        assert is_agent_available(AgentProvider.CLAUDE) is False

    def test_mock_available_in_test_mode(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test Mock availability in test mode."""
        monkeypatch.setenv("APP_ENVIRONMENT", "test")
        reset_settings()

        assert is_agent_available(AgentProvider.MOCK) is True
