"""Agent runner - main execution logic using claude-agent-sdk.

This is the core of the agent runner package. It uses the official
claude-agent-sdk for real tool execution (Bash, Read, Write, Edit).

It:
1. Loads task configuration
2. Sets up the Claude agent with workspace tools
3. Executes the task using claude-agent-sdk
4. Emits events for each tool use, turn, etc.
5. Writes output artifacts
6. Handles cancellation gracefully
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import TYPE_CHECKING, Any

from aef_agent_runner.cancellation import (
    CancellationError,
    CancellationToken,
    check_cancellation,
)
from aef_agent_runner.events import (
    emit_artifact,
    emit_cancelled,
    emit_completed,
    emit_error,
    emit_progress,
    emit_started,
    emit_token_usage,
)
from aef_agent_runner.hooks import create_hooks_config

if TYPE_CHECKING:
    from pathlib import Path

    from aef_agent_runner.task import Task

logger = logging.getLogger(__name__)

# Try to import claude-agent-sdk
try:
    from claude_agent_sdk import ClaudeAgentOptions, query

    # Import message types for proper event handling
    try:
        from claude_agent_sdk import AssistantMessage, ResultMessage, ToolUseBlock
    except ImportError:
        # Fallback if types aren't exported (older SDK versions)
        AssistantMessage = None  # type: ignore[assignment, misc]
        ResultMessage = None  # type: ignore[assignment, misc]
        ToolUseBlock = None  # type: ignore[assignment, misc]

    CLAUDE_SDK_AVAILABLE = True
except ImportError:
    CLAUDE_SDK_AVAILABLE = False
    query = None  # type: ignore[assignment]
    ClaudeAgentOptions = None  # type: ignore[assignment, misc]
    AssistantMessage = None  # type: ignore[assignment, misc]
    ResultMessage = None  # type: ignore[assignment, misc]
    ToolUseBlock = None  # type: ignore[assignment, misc]


class AgentRunner:
    """Runner for executing Claude agents inside isolated containers.

    The runner is designed to be the main entry point inside a workspace
    container. It reads task configuration, executes the agent using
    claude-agent-sdk with real tools, and emits events to stdout.
    """

    def __init__(
        self,
        task: Task,
        output_dir: Path,
        cancel_token: CancellationToken,
        *,
        max_turns: int = 50,
        model: str = "claude-sonnet-4-20250514",
    ) -> None:
        """Initialize the agent runner.

        Args:
            task: Task configuration
            output_dir: Directory for output artifacts
            cancel_token: Token for cancellation handling
            max_turns: Maximum conversation turns
            model: Claude model to use
        """
        self._task = task
        self._output_dir = output_dir
        self._cancel_token = cancel_token
        self._max_turns = max_turns
        self._model = model

        # Ensure output directory exists
        self._output_dir.mkdir(parents=True, exist_ok=True)

        # Track metrics
        self._turn_count = 0
        self._total_input_tokens = 0
        self._total_output_tokens = 0
        self._start_time: float | None = None

    def run(self) -> None:
        """Run the agent using claude-agent-sdk.

        This uses the official SDK which provides:
        - Built-in tools (Bash, Read, Write, Edit, etc.)
        - Proper tool execution in the workspace
        - Multi-turn autonomous operation

        Raises:
            CancellationError: If execution is cancelled
            RuntimeError: If claude-agent-sdk is not available
        """
        # Run the async implementation
        asyncio.run(self._run_async())

    async def _run_async(self) -> None:
        """Async implementation of the agent runner."""
        if not CLAUDE_SDK_AVAILABLE:
            emit_error(
                message="claude-agent-sdk not installed",
                error_type="ImportError",
            )
            raise RuntimeError("claude-agent-sdk is required but not installed")

        self._start_time = time.time()
        emit_started()

        try:
            # Check for cancellation
            check_cancellation(self._cancel_token)

            # Build the task prompt
            task_prompt = self._build_task_prompt()

            # Configure the agent
            workspace_dir = os.environ.get("WORKSPACE_DIR", "/workspace")

            # Create hooks for observability and safety
            # - Observability hooks: emit events to stdout (non-blocking)
            # - Safety hooks: validate tool calls (blocking, can deny)
            hooks_config = create_hooks_config(
                enable_observability=True,
                enable_safety=True,
            )

            # ANTHROPIC_API_KEY is read from environment by the SDK
            options = ClaudeAgentOptions(
                max_turns=self._max_turns,
                cwd=workspace_dir,
                model=self._model,
                # Bypass permission prompts - agent runs autonomously
                permission_mode="bypassPermissions",
                # Register hooks for observability and safety (type: ignore for flexible hook types)
                hooks=hooks_config if hooks_config else None,  # type: ignore[arg-type]
            )

            emit_progress(turn=0, input_tokens=0, output_tokens=0)

            # Execute using claude-agent-sdk's query function
            # This handles multi-turn execution with tools automatically
            async for event in query(prompt=task_prompt, options=options):
                # Check for cancellation between events
                check_cancellation(self._cancel_token)

                self._turn_count += 1
                self._handle_sdk_event(event)

            # Collect and emit artifacts
            self._collect_artifacts()

            # Emit completion
            duration_ms = int((time.time() - self._start_time) * 1000)
            emit_completed(success=True, duration_ms=duration_ms)

        except CancellationError:
            emit_cancelled()
            raise
        except Exception as e:
            logger.exception("Agent execution failed")
            emit_error(message=str(e), error_type=type(e).__name__)
            raise

    def _handle_sdk_event(self, event: Any) -> None:
        """Handle events from claude-agent-sdk.

        The SDK yields different message types:
        - AssistantMessage: Contains content blocks (text, tool_use)
        - ResultMessage: Final message with usage statistics

        This method extracts and emits observability events for:
        - Token usage (from ResultMessage.usage or AssistantMessage.usage)
        - Tool usage (from ToolUseBlock in AssistantMessage.content)
        """
        # Handle AssistantMessage - contains content blocks with tool_use
        if AssistantMessage is not None and isinstance(event, AssistantMessage):
            self._handle_assistant_message(event)
            return

        # Handle ResultMessage - contains final usage statistics
        if ResultMessage is not None and isinstance(event, ResultMessage):
            self._handle_result_message(event)
            return

        # Fallback: Handle legacy StreamEvent format (older SDK versions)
        if hasattr(event, "event"):
            self._handle_stream_event(event)
            return

        # Unknown event type - log for debugging
        logger.debug("Unknown SDK event type: %s", type(event).__name__)

    def _handle_assistant_message(self, message: Any) -> None:
        """Handle AssistantMessage from SDK.

        Note: Tool events (tool_use, tool_result) are now emitted by SDK hooks
        (PreToolUse, PostToolUse) to ensure consistent observability.
        This method only handles token usage tracking.
        """
        # Track usage if available on AssistantMessage
        if hasattr(message, "usage") and message.usage:
            usage = message.usage
            input_tokens = getattr(usage, "input_tokens", 0) or 0
            output_tokens = getattr(usage, "output_tokens", 0) or 0
            cache_creation = getattr(usage, "cache_creation_input_tokens", 0) or 0
            cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0

            if input_tokens > 0 or output_tokens > 0:
                self._total_input_tokens += input_tokens
                self._total_output_tokens += output_tokens
                emit_token_usage(
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cache_creation_tokens=cache_creation,
                    cache_read_tokens=cache_read,
                )

        # Note: Tool events are emitted via SDK hooks (PreToolUse, PostToolUse)
        # We only count tool blocks here for progress tracking
        tool_count = 0
        if hasattr(message, "content") and message.content:
            for block in message.content:
                if (ToolUseBlock is not None and isinstance(block, ToolUseBlock)) or (
                    isinstance(block, dict) and block.get("type") == "tool_use"
                ):
                    tool_count += 1

        if tool_count > 0:
            logger.debug("AssistantMessage contains %d tool_use blocks", tool_count)

        # Emit progress update
        emit_progress(
            turn=self._turn_count,
            input_tokens=self._total_input_tokens,
            output_tokens=self._total_output_tokens,
        )

    def _handle_result_message(self, message: Any) -> None:
        """Handle ResultMessage from SDK.

        This is the final message with complete usage statistics.
        """
        # Extract final usage statistics
        if hasattr(message, "usage") and message.usage:
            usage = message.usage
            # Handle both dict and object-style usage
            if isinstance(usage, dict):
                input_tokens = usage.get("input_tokens", 0)
                output_tokens = usage.get("output_tokens", 0)
                cache_creation = usage.get("cache_creation_input_tokens", 0)
                cache_read = usage.get("cache_read_input_tokens", 0)
            else:
                input_tokens = getattr(usage, "input_tokens", 0) or 0
                output_tokens = getattr(usage, "output_tokens", 0) or 0
                cache_creation = getattr(usage, "cache_creation_input_tokens", 0) or 0
                cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0

            # Emit token usage event
            if input_tokens > 0 or output_tokens > 0:
                self._total_input_tokens += input_tokens
                self._total_output_tokens += output_tokens
                emit_token_usage(
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cache_creation_tokens=cache_creation,
                    cache_read_tokens=cache_read,
                )

        # Log final progress
        emit_progress(
            turn=self._turn_count,
            input_tokens=self._total_input_tokens,
            output_tokens=self._total_output_tokens,
        )

        logger.debug(
            "ResultMessage: total_input=%d, total_output=%d",
            self._total_input_tokens,
            self._total_output_tokens,
        )

    def _handle_stream_event(self, event: Any) -> None:
        """Handle legacy StreamEvent format (older SDK versions).

        StreamEvent has: uuid, session_id, event (dict), parent_tool_use_id
        """
        event_data = event.event
        event_type = event_data.get("type", "")

        # Track usage if available
        if "usage" in event_data:
            usage = event_data["usage"]
            input_tokens = usage.get("input_tokens", 0)
            output_tokens = usage.get("output_tokens", 0)
            self._total_input_tokens += input_tokens
            self._total_output_tokens += output_tokens
            emit_token_usage(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            )

        # Log progress
        if event_type in ("message_start", "content_block_start", "message_stop"):
            emit_progress(
                turn=self._turn_count,
                input_tokens=self._total_input_tokens,
                output_tokens=self._total_output_tokens,
            )

    def _build_task_prompt(self) -> str:
        """Build the complete task prompt for the agent."""
        parts = []

        # Add the main prompt from task
        parts.append(self._task.prompt)

        # Add input context
        if self._task.inputs:
            parts.append("\n\n## Workflow Inputs")
            for key, value in self._task.inputs.items():
                parts.append(f"- **{key}**: {value}")

        # Add artifact info
        if self._task.artifacts:
            parts.append("\n\n## Available Input Artifacts")
            parts.append("Located in `/workspace/inputs/`:")
            for name in self._task.artifacts:
                parts.append(f"- {name}")

        # Add output instructions
        parts.append("\n\n## Output")
        parts.append("Write any output artifacts to `/workspace/artifacts/`")

        return "\n".join(parts)

    def _collect_artifacts(self) -> None:
        """Collect and emit artifact events for files in output directory."""
        if not self._output_dir.exists():
            return

        for path in self._output_dir.rglob("*"):
            if path.is_file():
                relative_path = path.relative_to(self._output_dir)
                emit_artifact(
                    name=str(relative_path),
                    path=str(path),
                    size_bytes=path.stat().st_size,
                )
