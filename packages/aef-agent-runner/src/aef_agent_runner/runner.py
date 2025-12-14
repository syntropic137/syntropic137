"""Agent runner - main execution logic.

This is the core of the agent runner package. It:
1. Loads task configuration
2. Sets up the Claude client
3. Executes the agent with the task prompt
4. Emits events for each tool use, turn, etc.
5. Writes output artifacts
6. Handles cancellation gracefully
"""

from __future__ import annotations

import logging
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
    from collections.abc import Iterator
    from pathlib import Path

    from anthropic import Anthropic

    from aef_agent_runner.task import Task

logger = logging.getLogger(__name__)


class AgentRunner:
    """Runner for executing Claude agents inside isolated containers.

    The runner is designed to be the main entry point inside a workspace
    container. It reads task configuration, executes the agent, and
    emits events to stdout for the orchestrator.
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

    def run(self) -> Iterator[dict[str, Any]]:
        """Run the agent and yield events.

        This is the main execution loop. It yields events as dictionaries
        that will be emitted as JSONL to stdout.

        Yields:
            Event dictionaries

        Raises:
            CancellationError: If execution is cancelled
        """
        self._start_time = time.time()
        emit_started()

        try:
            # Initialize the Anthropic client
            # Note: API key is injected by sidecar proxy, not in environment
            client = self._create_client()

            # Build the system prompt with task context
            system_prompt = self._task.build_system_prompt()

            # Execute the agent loop
            messages: list[dict[str, Any]] = []
            user_message = self._build_initial_message()
            messages.append({"role": "user", "content": user_message})

            for turn in range(self._max_turns):
                # Check for cancellation before each turn
                check_cancellation(self._cancel_token)

                self._turn_count = turn + 1
                emit_progress(
                    turn=self._turn_count,
                    input_tokens=self._total_input_tokens,
                    output_tokens=self._total_output_tokens,
                )

                # Call Claude
                response = client.messages.create(
                    model=self._model,
                    max_tokens=8192,
                    system=system_prompt,
                    messages=messages,
                )

                # Track token usage
                usage = response.usage
                self._total_input_tokens += usage.input_tokens
                self._total_output_tokens += usage.output_tokens
                emit_token_usage(
                    input_tokens=usage.input_tokens,
                    output_tokens=usage.output_tokens,
                    cache_creation_tokens=getattr(usage, "cache_creation_input_tokens", 0),
                    cache_read_tokens=getattr(usage, "cache_read_input_tokens", 0),
                )

                # Process response content
                assistant_content = []
                has_tool_use = False

                for block in response.content:
                    if block.type == "text":
                        assistant_content.append({"type": "text", "text": block.text})
                    elif block.type == "tool_use":
                        has_tool_use = True
                        tool_name = block.name
                        tool_input = block.input
                        tool_id = block.id

                        emit_tool_use(
                            tool_name=tool_name,
                            tool_input=tool_input,
                            tool_use_id=tool_id,
                        )

                        # Execute tool (simplified - real implementation would
                        # use actual tool execution)
                        tool_result = self._execute_tool(tool_name, tool_input, tool_id)

                        assistant_content.append(
                            {
                                "type": "tool_use",
                                "id": tool_id,
                                "name": tool_name,
                                "input": tool_input,
                            }
                        )

                        # Add tool result to messages
                        messages.append({"role": "assistant", "content": assistant_content})
                        messages.append(
                            {
                                "role": "user",
                                "content": [
                                    {
                                        "type": "tool_result",
                                        "tool_use_id": tool_id,
                                        "content": tool_result,
                                    }
                                ],
                            }
                        )
                        assistant_content = []

                # If no tool use, conversation is complete
                if not has_tool_use:
                    if assistant_content:
                        messages.append({"role": "assistant", "content": assistant_content})
                    break

                # Check stop reason
                if response.stop_reason == "end_turn":
                    break

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

    def _create_client(self) -> Anthropic:
        """Create the Anthropic client.

        Note: The API key is NOT in the environment. The sidecar proxy
        intercepts requests and injects the x-api-key header. We just
        need to ensure requests go through the proxy (HTTP_PROXY env var).
        """
        from anthropic import Anthropic

        # The client will use HTTP_PROXY/HTTPS_PROXY environment variables
        # to route through the sidecar, which injects the API key
        return Anthropic(
            # Use a placeholder - sidecar will inject the real key
            api_key="placeholder-sidecar-injects-key",
        )

    def _build_initial_message(self) -> str:
        """Build the initial user message."""
        parts = [f"Execute the {self._task.phase} phase."]

        if self._task.inputs:
            parts.append("\n\nWorkflow inputs:")
            for key, value in self._task.inputs.items():
                parts.append(f"- {key}: {value}")

        if self._task.artifacts:
            parts.append("\n\nInput artifacts available in /workspace/inputs/:")
            for name in self._task.artifacts:
                parts.append(f"- {name}")

        parts.append("\n\nWrite any output artifacts to /workspace/artifacts/")

        return "\n".join(parts)

    def _execute_tool(
        self,
        tool_name: str,
        tool_input: dict[str, Any],
        tool_id: str,
    ) -> str:
        """Execute a tool call.

        This is a simplified implementation. In a real setup, this would
        dispatch to actual tool implementations (Read, Write, Bash, etc.)

        For now, we emit events and return a placeholder result.
        """
        start_time = time.time()

        # Simplified tool execution
        # Real implementation would use claude-agent-sdk or similar
        result = f"Tool {tool_name} executed with input: {tool_input}"

        duration_ms = int((time.time() - start_time) * 1000)
        emit_tool_result(
            tool_name=tool_name,
            success=True,
            tool_use_id=tool_id,
            duration_ms=duration_ms,
        )

        return result

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
