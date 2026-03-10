"""Tests for agent adapters."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from syn_adapters.agents import (
    AgentConfig,
    AgentError,
    AgentMessage,
    AgentMetrics,
    AgentProtocol,
    AgentProvider,
    AgentResponse,
    AgentRole,
    MockAgent,
    MockAgentConfig,
    get_agent,
    get_available_agents,
    is_agent_available,
)

if TYPE_CHECKING:
    from pathlib import Path

# =============================================================================
# AgentMessage Tests
# =============================================================================


@pytest.mark.unit
class TestAgentMessage:
    """Tests for AgentMessage dataclass."""

    def test_create_user_message(self) -> None:
        """Test creating a user message."""
        msg = AgentMessage.user("Hello!")
        assert msg.role == AgentRole.USER
        assert msg.content == "Hello!"

    def test_create_assistant_message(self) -> None:
        """Test creating an assistant message."""
        msg = AgentMessage.assistant("Hi there!")
        assert msg.role == AgentRole.ASSISTANT
        assert msg.content == "Hi there!"

    def test_create_system_message(self) -> None:
        """Test creating a system message."""
        msg = AgentMessage.system("You are helpful.")
        assert msg.role == AgentRole.SYSTEM
        assert msg.content == "You are helpful."

    def test_message_is_immutable(self) -> None:
        """Test that AgentMessage is immutable."""
        msg = AgentMessage.user("Hello!")
        with pytest.raises(AttributeError):
            msg.content = "Changed"  # type: ignore[misc]


# =============================================================================
# AgentConfig Tests
# =============================================================================


class TestAgentConfig:
    """Tests for AgentConfig dataclass."""

    def test_default_config(self) -> None:
        """Test creating config with defaults."""
        config = AgentConfig(model="test-model")
        assert config.model == "test-model"
        assert config.max_tokens == 4096
        assert config.temperature == 0.7
        assert config.timeout_seconds == 300

    def test_custom_config(self) -> None:
        """Test creating config with custom values."""
        config = AgentConfig(
            model="custom-model",
            max_tokens=8192,
            temperature=0.0,
            timeout_seconds=60,
            system_prompt="Be helpful.",
        )
        assert config.max_tokens == 8192
        assert config.temperature == 0.0
        assert config.system_prompt == "Be helpful."

    def test_config_is_immutable(self) -> None:
        """Test that AgentConfig is immutable."""
        config = AgentConfig(model="test")
        with pytest.raises(AttributeError):
            config.model = "changed"  # type: ignore[misc]


# =============================================================================
# AgentResponse Tests
# =============================================================================


class TestAgentResponse:
    """Tests for AgentResponse dataclass."""

    def test_response_cost_estimate(self) -> None:
        """Test cost estimation calculation."""
        response = AgentResponse(
            content="Test",
            model="test-model",
            input_tokens=1000,
            output_tokens=500,
            total_tokens=1500,
        )
        # input: 1000/1000 * 0.01 = 0.01
        # output: 500/1000 * 0.03 = 0.015
        # total = 0.025
        assert response.cost_estimate == pytest.approx(0.025)

    def test_response_is_immutable(self) -> None:
        """Test that AgentResponse is immutable."""
        response = AgentResponse(
            content="Test",
            model="test",
            input_tokens=10,
            output_tokens=10,
            total_tokens=20,
        )
        with pytest.raises(AttributeError):
            response.content = "changed"  # type: ignore[misc]


# =============================================================================
# AgentMetrics Tests
# =============================================================================


class TestAgentMetrics:
    """Tests for AgentMetrics tracking."""

    def test_record_response(self) -> None:
        """Test recording metrics from responses."""
        metrics = AgentMetrics()
        response = AgentResponse(
            content="Test",
            model="test",
            input_tokens=100,
            output_tokens=50,
            total_tokens=150,
        )

        metrics.record(response)

        assert metrics.total_requests == 1
        assert metrics.total_input_tokens == 100
        assert metrics.total_output_tokens == 50
        assert metrics.total_tokens == 150

    def test_record_multiple_responses(self) -> None:
        """Test recording multiple responses."""
        metrics = AgentMetrics()

        for i in range(3):
            response = AgentResponse(
                content=f"Response {i}",
                model="test",
                input_tokens=100,
                output_tokens=50,
                total_tokens=150,
            )
            metrics.record(response)

        assert metrics.total_requests == 3
        assert metrics.total_input_tokens == 300
        assert metrics.total_output_tokens == 150
        assert metrics.total_tokens == 450

    def test_record_error(self) -> None:
        """Test recording errors."""
        metrics = AgentMetrics()
        metrics.record_error("Connection timeout")
        metrics.record_error("Rate limit exceeded")

        assert len(metrics.errors) == 2
        assert "Connection timeout" in metrics.errors


# =============================================================================
# MockAgent Tests
# =============================================================================


class TestMockAgent:
    """Tests for MockAgent implementation."""

    @pytest.mark.asyncio
    async def test_mock_agent_default_response(self) -> None:
        """Test mock agent returns default response."""
        agent = MockAgent()
        response = await agent.complete(
            messages=[AgentMessage.user("Hello")],
            config=AgentConfig(model="test"),
        )
        assert response.content == "Mock response"

    @pytest.mark.asyncio
    async def test_mock_agent_queued_responses(self) -> None:
        """Test mock agent returns queued responses in order."""
        config = MockAgentConfig(responses=["First", "Second", "Third"])
        agent = MockAgent(config)

        r1 = await agent.complete([AgentMessage.user("1")], AgentConfig(model="test"))
        r2 = await agent.complete([AgentMessage.user("2")], AgentConfig(model="test"))
        r3 = await agent.complete([AgentMessage.user("3")], AgentConfig(model="test"))
        r4 = await agent.complete([AgentMessage.user("4")], AgentConfig(model="test"))

        assert r1.content == "First"
        assert r2.content == "Second"
        assert r3.content == "Third"
        assert r4.content == "Mock response"  # Default after queue empty

    @pytest.mark.asyncio
    async def test_mock_agent_tracks_calls(self) -> None:
        """Test mock agent tracks call history."""
        agent = MockAgent()
        messages = [AgentMessage.user("Test")]
        config = AgentConfig(model="test")

        await agent.complete(messages, config)
        await agent.complete(messages, config)

        assert agent.call_count == 2
        assert len(agent.call_history) == 2
        assert agent.last_call is not None

    @pytest.mark.asyncio
    async def test_mock_agent_configured_failure(self) -> None:
        """Test mock agent can be configured to fail."""
        config = MockAgentConfig(fail_on_call=1, fail_error="Configured failure")
        agent = MockAgent(config)

        # First call succeeds
        await agent.complete([AgentMessage.user("1")], AgentConfig(model="test"))

        # Second call fails
        with pytest.raises(AgentError) as exc_info:
            await agent.complete([AgentMessage.user("2")], AgentConfig(model="test"))

        assert "Configured failure" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_mock_agent_streaming(self) -> None:
        """Test mock agent streaming."""
        config = MockAgentConfig(stream_chunks=["Hello ", "world", "!"])
        agent = MockAgent(config)

        chunks = []
        async for chunk in agent.stream([AgentMessage.user("Hi")], AgentConfig(model="test")):
            chunks.append(chunk)

        assert chunks == ["Hello ", "world", "!"]

    def test_mock_agent_implements_protocol(self) -> None:
        """Test mock agent implements AgentProtocol."""
        agent = MockAgent()
        assert isinstance(agent, AgentProtocol)

    def test_mock_agent_provider(self) -> None:
        """Test mock agent provider type."""
        agent = MockAgent()
        assert agent.provider == AgentProvider.MOCK

    def test_mock_agent_availability(self) -> None:
        """Test mock agent availability control."""
        agent = MockAgent()
        assert agent.is_available is True

        agent.set_available(False)
        assert agent.is_available is False


# =============================================================================
# Factory Tests
# =============================================================================


class TestAgentFactory:
    """Tests for agent factory functions."""

    def test_get_mock_agent(self) -> None:
        """Test getting mock agent explicitly."""
        agent = get_agent(AgentProvider.MOCK)
        assert agent.provider == AgentProvider.MOCK

    def test_get_available_agents_in_test_mode(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test available agents includes mock in test mode."""
        monkeypatch.setenv("APP_ENVIRONMENT", "test")
        # Clear settings cache to pick up new env
        from syn_shared.settings import reset_settings

        reset_settings()

        available = get_available_agents()
        assert AgentProvider.MOCK in available

    def test_is_agent_available_mock(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test checking mock agent availability."""
        monkeypatch.setenv("APP_ENVIRONMENT", "test")
        from syn_shared.settings import reset_settings

        reset_settings()

        assert is_agent_available(AgentProvider.MOCK) is True

    def test_claude_not_available_without_key(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Test Claude is not available without API key or OAuth token."""
        # Change to temp dir to avoid loading project .env file
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
        from syn_shared.settings import reset_settings

        reset_settings()

        assert is_agent_available(AgentProvider.CLAUDE) is False
