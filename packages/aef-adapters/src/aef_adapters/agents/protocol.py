"""Agent protocol - defines the interface for AI agent adapters.

All agent adapters (Claude, OpenAI, etc.) must implement this protocol.
This enables dependency injection and easy testing with mock agents.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


class AgentRole(str, Enum):
    """Role of the agent in the conversation."""

    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class AgentProvider(str, Enum):
    """Supported AI agent providers."""

    CLAUDE = "claude"
    OPENAI = "openai"
    MOCK = "mock"  # For testing


@dataclass(frozen=True)
class AgentMessage:
    """A message in an agent conversation.

    Immutable to ensure conversation history integrity.
    """

    role: AgentRole
    content: str

    @classmethod
    def user(cls, content: str) -> AgentMessage:
        """Create a user message."""
        return cls(role=AgentRole.USER, content=content)

    @classmethod
    def assistant(cls, content: str) -> AgentMessage:
        """Create an assistant message."""
        return cls(role=AgentRole.ASSISTANT, content=content)

    @classmethod
    def system(cls, content: str) -> AgentMessage:
        """Create a system message."""
        return cls(role=AgentRole.SYSTEM, content=content)


@dataclass(frozen=True)
class AgentConfig:
    """Configuration for an agent request.

    Immutable to prevent accidental modification during request processing.
    """

    model: str
    max_tokens: int = 4096
    temperature: float = 0.7
    timeout_seconds: int = 300
    system_prompt: str | None = None


@dataclass(frozen=True)
class AgentResponse:
    """Response from an agent.

    Contains the response content and usage metrics for tracking.
    """

    content: str
    model: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    stop_reason: str | None = None

    @property
    def cost_estimate(self) -> float:
        """Estimate cost in USD based on typical token pricing.

        Note: This is a rough estimate. Actual pricing varies by model.
        Claude: ~$0.008 per 1K input, ~$0.024 per 1K output
        GPT-4: ~$0.01 per 1K input, ~$0.03 per 1K output
        """
        # Conservative estimate using higher prices
        input_cost = (self.input_tokens / 1000) * 0.01
        output_cost = (self.output_tokens / 1000) * 0.03
        return input_cost + output_cost


@dataclass
class AgentMetrics:
    """Accumulated metrics for agent usage.

    Mutable to allow incrementing during a workflow.
    """

    total_requests: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_tokens: int = 0
    estimated_cost_usd: float = 0.0
    errors: list[str] = field(default_factory=list)

    def record(self, response: AgentResponse) -> None:
        """Record metrics from an agent response."""
        self.total_requests += 1
        self.total_input_tokens += response.input_tokens
        self.total_output_tokens += response.output_tokens
        self.total_tokens += response.total_tokens
        self.estimated_cost_usd += response.cost_estimate

    def record_error(self, error: str) -> None:
        """Record an error."""
        self.errors.append(error)


class AgentError(Exception):
    """Base exception for agent errors."""

    def __init__(self, message: str, provider: AgentProvider, retryable: bool = False) -> None:
        super().__init__(message)
        self.provider = provider
        self.retryable = retryable


class AgentRateLimitError(AgentError):
    """Rate limit exceeded - should retry with backoff."""

    def __init__(
        self, message: str, provider: AgentProvider, retry_after: float | None = None
    ) -> None:
        super().__init__(message, provider, retryable=True)
        self.retry_after = retry_after


class AgentAuthenticationError(AgentError):
    """Authentication failed - check API key."""

    def __init__(self, message: str, provider: AgentProvider) -> None:
        super().__init__(message, provider, retryable=False)


class AgentTimeoutError(AgentError):
    """Request timed out."""

    def __init__(self, message: str, provider: AgentProvider) -> None:
        super().__init__(message, provider, retryable=True)


@runtime_checkable
class AgentProtocol(Protocol):
    """Protocol for AI agent adapters.

    All agent implementations must provide these methods.
    Using Protocol enables structural subtyping (duck typing with type hints).
    """

    @property
    def provider(self) -> AgentProvider:
        """Get the agent provider type."""
        ...

    @property
    def is_available(self) -> bool:
        """Check if the agent is configured and available."""
        ...

    async def complete(
        self,
        messages: list[AgentMessage],
        config: AgentConfig,
    ) -> AgentResponse:
        """Send messages to the agent and get a response.

        Args:
            messages: Conversation history.
            config: Request configuration.

        Returns:
            Agent response with content and metrics.

        Raises:
            AgentError: If the request fails.
        """
        ...

    def stream(
        self,
        messages: list[AgentMessage],
        config: AgentConfig,
    ) -> AsyncIterator[str]:
        """Stream a response from the agent.

        Note: This is an async generator, not an async function.
        Implementations should use `async def` which returns AsyncIterator.

        Args:
            messages: Conversation history.
            config: Request configuration.

        Yields:
            Response content chunks.

        Raises:
            AgentError: If the request fails.
        """
        ...
