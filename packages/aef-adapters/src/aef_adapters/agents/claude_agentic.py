"""Claude Agentic Agent - implements AgenticProtocol using claude-agent-sdk.

This is the recommended agent adapter for Claude, using the official
agentic SDK for multi-turn autonomous execution with built-in tool support.

Unlike the legacy ClaudeAgent (chat completion), this agent:
- Executes tasks autonomously until completion
- Uses built-in tools (Read, Write, Bash, Edit, etc.)
- Supports security hooks via workspace configuration
- Streams events as it works
- Controls its own execution flow

Example:
    agent = ClaudeAgenticAgent(model="claude-sonnet-4-5-20250929")

    async with LocalWorkspace.create(config) as workspace:
        async for event in agent.execute(
            task="Create a hello.py file that prints 'Hello, World!'",
            workspace=workspace,
            config=AgentExecutionConfig(max_turns=10),
        ):
            if isinstance(event, TaskCompleted):
                print(f"Done: {event.result}")
"""

from __future__ import annotations

import logging
import os
import time
from typing import TYPE_CHECKING

from aef_adapters.agents.agentic_protocol import (
    AgenticSDKError,
    AgenticTimeoutError,
)
from aef_adapters.agents.agentic_types import (
    AgentExecutionConfig,
    AgentTool,
    TaskCompleted,
    TaskFailed,
    TextOutput,
    ToolUseCompleted,
    ToolUseStarted,
    Workspace,
)
from aef_adapters.agents.protocol import AgentProvider

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from aef_adapters.agents.agentic_types import AgentEvent

logger = logging.getLogger(__name__)

# Try to import claude-agent-sdk (optional dependency)
try:
    from claude_agent_sdk import (
        AssistantMessage,
        ClaudeAgentOptions,
        ResultMessage,
        ToolUseBlock,
        query,
    )

    CLAUDE_SDK_AVAILABLE = True
except ImportError:
    CLAUDE_SDK_AVAILABLE = False
    # Placeholders when SDK not installed (only used at runtime, not type checking)
    AssistantMessage = None
    ClaudeAgentOptions = None
    ResultMessage = None
    ToolUseBlock = None
    query = None


class ClaudeAgenticAgent:
    """Claude agentic agent using claude-agent-sdk.

    Implements the AgenticProtocol for true agentic execution.
    Uses the official claude-agent-sdk for multi-turn autonomous operation.
    """

    # Default model for Claude agentic execution
    DEFAULT_MODEL = "claude-sonnet-4-5-20250929"

    # Standard tools supported by claude-agent-sdk
    SUPPORTED_TOOLS: frozenset[str] = frozenset(AgentTool.all())

    def __init__(
        self,
        model: str | None = None,
        api_key: str | None = None,
    ) -> None:
        """Initialize Claude agentic agent.

        Args:
            model: Model name (default: claude-sonnet-4-5-20250929)
            api_key: Anthropic API key (defaults to ANTHROPIC_API_KEY env var)
        """
        self._model = model or self.DEFAULT_MODEL
        self._api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")

    @property
    def provider(self) -> AgentProvider:
        """Get the agent provider type."""
        return AgentProvider.CLAUDE

    @property
    def supported_tools(self) -> frozenset[str]:
        """Get the tools this agent can use."""
        return self.SUPPORTED_TOOLS

    @property
    def is_available(self) -> bool:
        """Check if the agent is configured and available.

        Returns True if:
        - claude-agent-sdk is installed
        - ANTHROPIC_API_KEY is set
        """
        return CLAUDE_SDK_AVAILABLE and bool(self._api_key)

    async def execute(
        self,
        task: str,
        workspace: Workspace,
        config: AgentExecutionConfig,
    ) -> AsyncIterator[AgentEvent]:
        """Execute a task in the workspace, yielding events until done.

        Args:
            task: Natural language description of the task
            workspace: Isolated execution environment with hooks configured
            config: Execution configuration (tools, limits, etc.)

        Yields:
            AgentEvent stream representing execution progress

        Raises:
            AgenticSDKError: If the SDK is not available or API key not set
            AgenticTimeoutError: If execution times out
            AgenticError: For other execution failures
        """
        if not CLAUDE_SDK_AVAILABLE:
            raise AgenticSDKError(
                "claude-agent-sdk is not installed. "
                "Install with: pip install aef-adapters[claude-agentic]",
                provider=self.provider,
            )

        if not self._api_key:
            raise AgenticSDKError(
                "ANTHROPIC_API_KEY environment variable not set",
                provider=self.provider,
            )

        # Build allowed tools list
        allowed_tools = (
            list(config.allowed_tools) if config.allowed_tools else list(AgentTool.all())
        )

        # Configure agent options
        options = ClaudeAgentOptions(
            model=self._model,
            cwd=str(workspace.path),
            allowed_tools=allowed_tools,
            permission_mode=config.permission_mode,
            setting_sources=list(config.setting_sources),
            max_turns=config.max_turns,
            max_budget_usd=config.max_budget_usd,
        )

        # Track execution state
        start_time = time.time()
        tool_calls: list[str] = []
        turns_used = 0
        current_tool_id: str | None = None

        try:
            result_text = ""
            input_tokens = 0
            output_tokens = 0

            # Stream the query
            async for message in query(prompt=task, options=options):
                if isinstance(message, AssistantMessage):
                    turns_used += 1

                    # Process content blocks
                    if hasattr(message, "content") and message.content:
                        for block in message.content:
                            if isinstance(block, ToolUseBlock):
                                # Emit tool use started event
                                current_tool_id = getattr(block, "id", None)
                                tool_input = getattr(block, "input", {}) or {}

                                yield ToolUseStarted(
                                    tool_name=block.name,
                                    tool_input=tool_input,
                                    tool_use_id=current_tool_id,
                                )

                                tool_calls.append(block.name)

                                # TODO: Capture tool output from ToolResultBlock
                                # For now, emit completed without output
                                yield ToolUseCompleted(
                                    tool_name=block.name,
                                    tool_use_id=current_tool_id,
                                    success=True,
                                )

                            elif hasattr(block, "text"):
                                # Text content from assistant
                                yield TextOutput(
                                    content=block.text,
                                    is_partial=True,
                                )

                elif isinstance(message, ResultMessage):
                    result_text = message.result or ""

                    # Extract token usage
                    if message.usage:
                        input_tokens = message.usage.get("input_tokens", 0)
                        output_tokens = message.usage.get("output_tokens", 0)

            # Calculate final metrics
            duration_ms = (time.time() - start_time) * 1000
            total_tokens = input_tokens + output_tokens

            # Emit task completed
            yield TaskCompleted(
                result=result_text,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=total_tokens,
                turns_used=turns_used,
                tools_used=tool_calls,
                duration_ms=duration_ms,
                # TODO: Add cost estimation from model config
                estimated_cost_usd=None,
            )

        except TimeoutError as e:
            duration_ms = (time.time() - start_time) * 1000
            raise AgenticTimeoutError(
                f"Execution timed out after {config.timeout_seconds}s",
                provider=self.provider,
                timeout_seconds=config.timeout_seconds,
            ) from e

        except Exception as e:
            # Handle any other SDK errors
            duration_ms = (time.time() - start_time) * 1000

            yield TaskFailed(
                error=str(e),
                error_type="sdk_error",
                partial_result=result_text if "result_text" in dir() else None,
                input_tokens=input_tokens if "input_tokens" in dir() else 0,
                output_tokens=output_tokens if "output_tokens" in dir() else 0,
                turns_used=turns_used,
                duration_ms=duration_ms,
            )


# Alias for backwards compatibility
ClaudeAgent = ClaudeAgenticAgent
