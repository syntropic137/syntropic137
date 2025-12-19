"""Mock agent adapter for TESTING ONLY.

WARNING: MockAgent is for unit/integration tests only.
For local development and production, use real agent adapters (Claude, OpenAI).

The MockAgent:
- Does NOT call real AI APIs
- Should NEVER be used outside of tests
- Will raise MockAgentError if used in non-test environments
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from aef_adapters.agents.protocol import (
    AgentConfig,
    AgentError,
    AgentMessage,
    AgentProtocol,
    AgentProvider,
    AgentResponse,
)
from aef_shared.settings import get_settings

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


class MockAgentError(Exception):
    """Raised when MockAgent is used outside of test environment."""

    pass


def _assert_test_environment() -> None:
    """Assert that we're in a test environment.

    Raises:
        MockAgentError: If not in test environment (APP_ENVIRONMENT != 'test').
    """
    settings = get_settings()
    if not settings.is_test:
        raise MockAgentError(
            f"MockAgent can ONLY be used in test environments. "
            f"Current environment: {settings.app_environment}. "
            f"For local development, set ANTHROPIC_API_KEY and use real agents. "
            f"For testing, set APP_ENVIRONMENT=test"
        )


@dataclass
class MockAgentConfig:
    """Configuration for mock agent behavior.

    Attributes:
        responses: Queue of responses to return (FIFO).
        default_response: Response when queue is empty.
        fail_on_call: Raise error on next call.
        stream_chunks: Chunks to yield when streaming.
    """

    responses: list[str] = field(default_factory=list)
    default_response: str = "Mock response"
    fail_on_call: int | None = None  # Fail on Nth call (0-indexed)
    fail_error: str = "Mock error"
    stream_chunks: list[str] = field(default_factory=lambda: ["Mock ", "streaming ", "response"])

    # Track calls
    call_count: int = field(default=0, init=False)
    call_history: list[tuple[list[AgentMessage], AgentConfig]] = field(
        default_factory=list, init=False
    )


class MockAgent(AgentProtocol):
    """Mock agent for testing.

    Usage in tests:
        mock_config = MockAgentConfig(responses=["Hello!", "Goodbye!"])
        agent = MockAgent(mock_config)

        # First call returns "Hello!"
        response = await agent.complete(messages, config)

        # Second call returns "Goodbye!"
        response = await agent.complete(messages, config)

        # Third call returns default_response
        response = await agent.complete(messages, config)

    Configure failures:
        mock_config = MockAgentConfig(fail_on_call=0, fail_error="API down")
        agent = MockAgent(mock_config)
        # First call raises AgentError
    """

    def __init__(self, config: MockAgentConfig | None = None) -> None:
        """Initialize mock agent with optional configuration.

        Raises:
            MockAgentError: If not in test environment.
        """
        _assert_test_environment()
        self._config = config or MockAgentConfig()
        self._available = True

    @property
    def provider(self) -> AgentProvider:
        """Get the agent provider type."""
        return AgentProvider.MOCK

    @property
    def is_available(self) -> bool:
        """Check if the agent is available."""
        return self._available

    def set_available(self, available: bool) -> None:
        """Set agent availability (for testing)."""
        self._available = available

    def set_session_context(
        self,
        *,
        session_id: str,
        workflow_id: str,
        phase_id: str,
    ) -> None:
        """Set session context (no-op for mock agent)."""
        pass  # Mock doesn't need context

    async def complete(
        self,
        messages: list[AgentMessage],
        config: AgentConfig,
    ) -> AgentResponse:
        """Return a mock response.

        Tracks calls and returns queued or default responses.
        """
        # Record call
        self._config.call_count += 1
        self._config.call_history.append((messages.copy(), config))

        # Check for configured failure
        call_index = self._config.call_count - 1
        if self._config.fail_on_call == call_index:
            raise AgentError(self._config.fail_error, AgentProvider.MOCK)

        # Get response
        if self._config.responses:
            content = self._config.responses.pop(0)
        else:
            content = self._config.default_response

        return AgentResponse(
            content=content,
            model="mock-model",
            input_tokens=len(str(messages)) // 4,  # Rough token estimate
            output_tokens=len(content) // 4,
            total_tokens=(len(str(messages)) + len(content)) // 4,
            stop_reason="end_turn",
        )

    async def stream(
        self,
        messages: list[AgentMessage],
        config: AgentConfig,
    ) -> AsyncIterator[str]:
        """Yield mock streaming chunks.

        Tracks calls and yields configured chunks.
        """
        # Record call
        self._config.call_count += 1
        self._config.call_history.append((messages.copy(), config))

        # Check for configured failure
        call_index = self._config.call_count - 1
        if self._config.fail_on_call == call_index:
            raise AgentError(self._config.fail_error, AgentProvider.MOCK)

        # Yield chunks
        for chunk in self._config.stream_chunks:
            yield chunk

    def reset(self) -> None:
        """Reset call tracking."""
        self._config.call_count = 0
        self._config.call_history = []

    @property
    def call_count(self) -> int:
        """Get number of calls made."""
        return self._config.call_count

    @property
    def call_history(self) -> list[tuple[list[AgentMessage], AgentConfig]]:
        """Get history of all calls."""
        return self._config.call_history

    @property
    def last_call(self) -> tuple[list[AgentMessage], AgentConfig] | None:
        """Get the most recent call."""
        return self._config.call_history[-1] if self._config.call_history else None
