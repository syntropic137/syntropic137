"""Agentic protocol - interface for agentic task execution.

This protocol defines the interface for true agentic execution, where agents:
- Execute tasks autonomously until completion
- Use tools (Read, Write, Bash, Edit, etc.)
- Have built-in hook support via configuration
- Control their own execution flow
- Stream events as they work

This is fundamentally different from the AgentProtocol (chat completion model)
which uses single request/response patterns.

See ADR-009 for the architectural decision behind this paradigm shift.
"""

from __future__ import annotations

from abc import abstractmethod
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from aef_adapters.agents.agentic_types import (
        AgentEvent,
        AgentExecutionConfig,
        Workspace,
    )
    from aef_adapters.agents.protocol import AgentProvider


@runtime_checkable
class AgenticProtocol(Protocol):
    """Protocol for agentic task execution.

    Unlike AgentProtocol (chat completion), this protocol supports:
    - Multi-turn execution until task completion
    - Tool use (Read, Write, Bash, Edit, etc.)
    - Automatic hook firing via workspace configuration
    - Streaming events during execution
    - Agent-controlled flow (agent decides when done)

    Implementations should use agentic SDKs (like claude-agent-sdk)
    rather than raw LLM APIs.

    Example:
        agent = ClaudeAgent(model="claude-sonnet")
        workspace = LocalWorkspace.create(config)

        async for event in agent.execute(
            task="Create a hello.py file that prints 'Hello, World!'",
            workspace=workspace,
            config=AgentExecutionConfig(max_turns=10),
        ):
            if isinstance(event, ToolUseCompleted):
                print(f"Tool: {event.tool_name}")
            elif isinstance(event, TaskCompleted):
                print(f"Done: {event.result}")
    """

    @property
    @abstractmethod
    def provider(self) -> AgentProvider:
        """Get the agent provider type.

        Returns:
            The provider enum (CLAUDE, OPENAI, etc.)
        """
        ...

    @property
    @abstractmethod
    def supported_tools(self) -> frozenset[str]:
        """Get the tools this agent can use.

        Returns:
            Set of tool names (Read, Write, Bash, etc.)
        """
        ...

    @property
    @abstractmethod
    def is_available(self) -> bool:
        """Check if the agent is configured and available.

        Returns:
            True if API credentials are set and SDK is available.
        """
        ...

    @abstractmethod
    def execute(
        self,
        task: str,
        workspace: Workspace,
        config: AgentExecutionConfig,
    ) -> AsyncIterator[AgentEvent]:
        """Execute a task in the workspace, yielding events until done.

        The agent decides:
        - How many turns to take (up to config.max_turns)
        - Which tools to use (from config.allowed_tools)
        - When the task is complete

        The caller provides:
        - Task description (what to accomplish)
        - Workspace with context injected
        - Configuration (tools, hooks, budget limits)

        Events are streamed as the agent works:
        - ToolUseStarted/ToolUseCompleted for tool calls
        - ToolBlocked if a security hook blocks a tool
        - ThinkingUpdate for agent reasoning (if available)
        - TextOutput for streaming text responses
        - TaskCompleted or TaskFailed as final events

        Args:
            task: Natural language description of what to accomplish.
            workspace: Isolated execution environment with hooks configured.
            config: Execution configuration (tools, limits, behavior).

        Yields:
            AgentEvent stream representing execution progress.

        Raises:
            AgentError: If execution fails critically.

        Example:
            async for event in agent.execute(task, workspace, config):
                match event:
                    case ToolUseStarted(tool_name=name):
                        print(f"Using {name}...")
                    case TaskCompleted(result=result):
                        print(f"Result: {result}")
                    case TaskFailed(error=error):
                        print(f"Failed: {error}")
        """
        ...


class AgenticError(Exception):
    """Base exception for agentic execution errors."""

    def __init__(
        self,
        message: str,
        provider: AgentProvider,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.provider = provider
        self.retryable = retryable


class AgenticBudgetExceededError(AgenticError):
    """Budget limit was exceeded during execution."""

    def __init__(
        self,
        message: str,
        provider: AgentProvider,
        spent_usd: float,
        budget_usd: float,
    ) -> None:
        super().__init__(message, provider, retryable=False)
        self.spent_usd = spent_usd
        self.budget_usd = budget_usd


class AgenticTurnsExceededError(AgenticError):
    """Max turns limit was exceeded during execution."""

    def __init__(
        self,
        message: str,
        provider: AgentProvider,
        turns_used: int,
        max_turns: int,
    ) -> None:
        super().__init__(message, provider, retryable=False)
        self.turns_used = turns_used
        self.max_turns = max_turns


class AgenticTimeoutError(AgenticError):
    """Execution timed out."""

    def __init__(
        self,
        message: str,
        provider: AgentProvider,
        timeout_seconds: int,
    ) -> None:
        super().__init__(message, provider, retryable=True)
        self.timeout_seconds = timeout_seconds


class AgenticSDKError(AgenticError):
    """Error from the underlying agentic SDK."""

    def __init__(
        self,
        message: str,
        provider: AgentProvider,
        sdk_error: Exception | None = None,
    ) -> None:
        super().__init__(message, provider, retryable=False)
        self.sdk_error = sdk_error
