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
    emit_tool_result,
    emit_tool_use,
)

if TYPE_CHECKING:
    from pathlib import Path

    from aef_agent_runner.task import Task

logger = logging.getLogger(__name__)

# Try to import claude-agent-sdk
try:
    from claude_agent_sdk import ClaudeAgentOptions, query
    from claude_agent_sdk.types import (
        AssistantMessage,
        ResultMessage,
        ToolResultMessage,
        ToolUseBlock,
    )

    CLAUDE_SDK_AVAILABLE = True
except ImportError:
    CLAUDE_SDK_AVAILABLE = False
    query = None
    ClaudeAgentOptions = None
    AssistantMessage = None
    ResultMessage = None
    ToolResultMessage = None
    ToolUseBlock = None


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
            # Use cwd to set the working directory for tool execution
            workspace_dir = os.environ.get("WORKSPACE_DIR", "/workspace")

            options = ClaudeAgentOptions(
                max_turns=self._max_turns,
                cwd=workspace_dir,
                # The API key is injected by the sidecar proxy
                # We pass a placeholder that the proxy replaces
                api_key=os.environ.get(
                    "ANTHROPIC_API_KEY", "placeholder-sidecar-injects"
                ),
                model=self._model,
            )

            emit_progress(turn=0, input_tokens=0, output_tokens=0)

            # Execute using claude-agent-sdk's query function
            # This handles multi-turn execution with tools automatically
            for event in query(task_prompt, options=options):
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
        - AssistantMessage: Claude's response with potential tool uses
        - ToolResultMessage: Results of tool execution
        - ResultMessage: Final result when task is complete
        """
        # Handle based on message type
        if AssistantMessage is not None and isinstance(event, AssistantMessage):
            # Check for tool use blocks
            if hasattr(event, "content") and event.content:
                for block in event.content:
                    if ToolUseBlock is not None and isinstance(block, ToolUseBlock):
                        emit_tool_use(
                            tool_name=block.name,
                            tool_input=block.input if hasattr(block, "input") else {},
                            tool_use_id=block.id,
                        )

            # Track tokens if available
            if hasattr(event, "usage") and event.usage:
                input_tokens = getattr(event.usage, "input_tokens", 0)
                output_tokens = getattr(event.usage, "output_tokens", 0)
                self._total_input_tokens += input_tokens
                self._total_output_tokens += output_tokens
                emit_token_usage(
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                )

            emit_progress(
                turn=self._turn_count,
                input_tokens=self._total_input_tokens,
                output_tokens=self._total_output_tokens,
            )

        elif ToolResultMessage is not None and isinstance(event, ToolResultMessage):
            # Tool result - extract success/failure info
            if hasattr(event, "content") and event.content:
                for result in event.content:
                    tool_id = getattr(result, "tool_use_id", "unknown")
                    is_error = getattr(result, "is_error", False)
                    emit_tool_result(
                        tool_name="tool",  # SDK doesn't include name in result
                        success=not is_error,
                        tool_use_id=tool_id,
                        duration_ms=0,  # Not tracked by SDK
                    )

        elif ResultMessage is not None and isinstance(event, ResultMessage):
            # Final result - task complete
            if hasattr(event, "usage") and event.usage:
                input_tokens = getattr(event.usage, "input_tokens", 0)
                output_tokens = getattr(event.usage, "output_tokens", 0)
                self._total_input_tokens += input_tokens
                self._total_output_tokens += output_tokens
                emit_token_usage(
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
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
