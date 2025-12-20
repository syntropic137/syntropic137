"""Container Agent Runner - Execute agents inside Docker and capture JSONL events.

ADR-029: Simplified Event System - This bridges containerized execution with
the new JSONL event system for storage in TimescaleDB.

This module provides an agent runner that:
1. Runs the claude CLI inside a Docker container
2. Streams stdout line by line
3. Parses JSONL events from hooks and Claude output
4. Stores events in AgentEventStore via EventBuffer

This bridges the gap between containerized execution and the new event system (ADR-029).

Usage:
    runner = ContainerAgentRunner(event_buffer)

    async for event in runner.execute(
        task="Create hello.py",
        workspace=managed_workspace,
        session_id="abc123",
    ):
        handle_event(event)
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from aef_adapters.events.buffer import EventBuffer
    from aef_adapters.workspace_backends.service import ManagedWorkspace

logger = logging.getLogger(__name__)


@dataclass
class ContainerExecutionResult:
    """Result from container agent execution."""

    success: bool
    output: str
    error: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    duration_seconds: float = 0.0
    estimated_cost_usd: Decimal | None = None
    tool_count: int = 0


def _extract_tool_uses(event: dict[str, Any]) -> dict[str, str]:
    """Extract tool_use_id → tool_name mappings from assistant messages.

    Claude CLI emits tool_use in assistant message content, but tool_result
    in user messages only has tool_use_id (no tool_name). We need to track
    the mapping to enrich tool_result events.

    Args:
        event: Raw Claude CLI event (type: "assistant" with tool_use content)

    Returns:
        Dict mapping tool_use_id to tool_name
    """
    tool_names: dict[str, str] = {}

    message = event.get("message", {})
    content = message.get("content", [])

    if not isinstance(content, list):
        return tool_names

    for item in content:
        if isinstance(item, dict) and item.get("type") == "tool_use":
            tool_id = item.get("id")
            tool_name = item.get("name")
            if tool_id and tool_name:
                tool_names[tool_id] = tool_name

    return tool_names


def _enrich_tool_result(
    event: dict[str, Any], tool_names: dict[str, str]
) -> dict[str, Any]:
    """Enrich tool_result events with tool_name from cache.

    Claude CLI's tool_result (in user messages) only has tool_use_id.
    We look up the tool_name from the cached mappings.

    Args:
        event: Raw Claude CLI event
        tool_names: Mapping of tool_use_id → tool_name

    Returns:
        Enriched event with tool_name added if applicable
    """
    message = event.get("message", {})
    content = message.get("content", [])

    if not isinstance(content, list):
        return event

    enriched = False
    for item in content:
        if isinstance(item, dict) and item.get("type") == "tool_result":
            tool_id = item.get("tool_use_id")
            if tool_id and tool_id in tool_names:
                item["tool_name"] = tool_names[tool_id]
                enriched = True

    if enriched:
        # Return a modified copy
        return {**event, "message": {**message, "content": content}}
    return event


@dataclass
class ContainerExecutionConfig:
    """Configuration for container agent execution."""

    max_turns: int = 50
    timeout_seconds: int = 3600
    allowed_tools: list[str] | None = None
    permission_mode: str = "bypassPermissions"


# Execution events yielded during streaming
@dataclass
class ContainerToolStarted:
    """Tool execution started inside container."""

    tool_name: str
    tool_input: dict[str, Any] | None
    tool_use_id: str | None
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class ContainerToolCompleted:
    """Tool execution completed inside container."""

    tool_name: str
    tool_use_id: str | None
    success: bool
    duration_ms: int | None = None
    error: str | None = None


@dataclass
class ContainerTurnCompleted:
    """Turn completed inside container."""

    turn_number: int
    input_tokens: int
    output_tokens: int
    cumulative_input_tokens: int
    cumulative_output_tokens: int


@dataclass
class ContainerOutput:
    """Text output from agent."""

    content: str
    is_partial: bool = False


@dataclass
class ContainerCompleted:
    """Agent execution completed."""

    result: ContainerExecutionResult


@dataclass
class ContainerFailed:
    """Agent execution failed."""

    error: str
    error_type: str = "ContainerError"
    partial_result: ContainerExecutionResult | None = None


# Type alias for execution events
ContainerEvent = (
    ContainerToolStarted
    | ContainerToolCompleted
    | ContainerTurnCompleted
    | ContainerOutput
    | ContainerCompleted
    | ContainerFailed
)


class ContainerAgentRunner:
    """Run Claude agent inside a container and capture JSONL events.

    This runner:
    1. Streams stdout from `claude -p <task> --output-format stream-json`
    2. Parses each line as JSON
    3. Yields execution events for real-time UI
    4. Stores events in EventBuffer for persistence

    Example:
        from aef_adapters.agents.container_runner import ContainerAgentRunner
        from aef_adapters.events import get_event_store, EventBuffer

        store = get_event_store()
        await store.initialize()
        buffer = EventBuffer(store)
        await buffer.start()

        runner = ContainerAgentRunner(buffer)

        async for event in runner.execute(
            task="Create hello.py",
            workspace=managed_workspace,
            session_id="session-123",
        ):
            print(event)

        await buffer.stop()
    """

    def __init__(
        self,
        event_buffer: EventBuffer | None = None,
        claude_command: str = "claude",
    ) -> None:
        """Initialize the container agent runner.

        Args:
            event_buffer: Optional EventBuffer for storing events
            claude_command: Claude CLI command (default: "claude")
        """
        self._buffer = event_buffer
        self._claude_command = claude_command

    async def execute(
        self,
        task: str,
        workspace: ManagedWorkspace,
        config: ContainerExecutionConfig | None = None,
        *,
        session_id: str,
        execution_id: str | None = None,
        phase_id: str | None = None,
    ) -> AsyncIterator[ContainerEvent]:
        """Execute an agent task inside the container.

        Args:
            task: Natural language task description
            workspace: ManagedWorkspace with Docker isolation
            config: Execution configuration
            session_id: Session ID for event correlation
            execution_id: Optional execution ID
            phase_id: Optional phase ID

        Yields:
            ContainerEvent instances as execution progresses
        """
        import time

        config = config or ContainerExecutionConfig()
        start_time = time.monotonic()

        # Build claude CLI command
        cmd = self._build_command(task, config)

        # Track metrics
        total_input_tokens = 0
        total_output_tokens = 0
        tool_count = 0
        result_text = ""
        error_message: str | None = None
        turn_number = 0
        estimated_cost: Decimal | None = None

        # Track tool_use_id → tool_name for enriching tool_result events
        # Claude CLI's tool_result only has tool_use_id, not tool_name
        tool_names: dict[str, str] = {}

        # Emit session_started event
        await self._store_event(
            {
                "event_type": "session_started",
                "session_id": session_id,
                "task": task[:1000],  # Truncate long tasks
                "timestamp": datetime.now(UTC).isoformat(),
            },
            execution_id,
            phase_id,
        )

        try:
            # Stream stdout from container
            async for line in workspace.stream(
                cmd,
                timeout_seconds=config.timeout_seconds,
                environment={
                    "CLAUDE_SESSION_ID": session_id,
                    "AEF_EXECUTION_ID": execution_id or "",
                    "AEF_PHASE_ID": phase_id or "",
                },
            ):
                # Parse JSON line
                event = self._parse_line(line)
                if event is None:
                    continue

                event_type = event.get("type") or event.get("event_type")

                # Extract tool names from assistant messages for later enrichment
                # Claude CLI's assistant messages contain tool_use with id and name
                if event_type == "assistant":
                    extracted = _extract_tool_uses(event)
                    tool_names.update(extracted)
                    if extracted:
                        logger.debug("Cached tool names: %s", extracted)

                # Enrich user messages (tool_result) with tool_name
                # Claude CLI's tool_result only has tool_use_id, not tool_name
                if event_type == "user":
                    event = _enrich_tool_result(event, tool_names)

                # Store event (now enriched with tool_name if applicable)
                await self._store_event(
                    {**event, "session_id": session_id},
                    execution_id,
                    phase_id,
                )

                # Yield appropriate event
                if event_type == "tool_use_started":
                    yield ContainerToolStarted(
                        tool_name=event.get("tool_name", "unknown"),
                        tool_input=event.get("tool_input"),
                        tool_use_id=event.get("tool_use_id"),
                    )

                elif event_type == "tool_use_completed":
                    tool_count += 1
                    yield ContainerToolCompleted(
                        tool_name=event.get("tool_name", "unknown"),
                        tool_use_id=event.get("tool_use_id"),
                        success=event.get("success", True),
                        duration_ms=event.get("duration_ms"),
                        error=event.get("error"),
                    )

                elif event_type == "turn_completed":
                    turn_number += 1
                    input_tokens = event.get("input_tokens", 0)
                    output_tokens = event.get("output_tokens", 0)
                    total_input_tokens += input_tokens
                    total_output_tokens += output_tokens

                    yield ContainerTurnCompleted(
                        turn_number=turn_number,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        cumulative_input_tokens=total_input_tokens,
                        cumulative_output_tokens=total_output_tokens,
                    )

                elif event_type == "text_output":
                    content = event.get("content", "")
                    yield ContainerOutput(
                        content=content,
                        is_partial=event.get("is_partial", False),
                    )
                    if not event.get("is_partial"):
                        result_text += content

                elif event_type == "result":
                    # Claude CLI final result message
                    result_text = event.get("result", result_text)
                    if "cost_usd" in event:
                        estimated_cost = Decimal(str(event["cost_usd"]))
                    if "input_tokens" in event:
                        total_input_tokens = event["input_tokens"]
                    if "output_tokens" in event:
                        total_output_tokens = event["output_tokens"]

                elif event_type == "error":
                    error_message = event.get("error", "Unknown error")

                # Hook events (from agentic_events)
                elif event_type in (
                    "tool_execution_started",
                    "tool_execution_completed",
                    "token_usage",
                ):
                    # Already stored above, just log for visibility
                    logger.debug("Hook event: %s", event_type)

        except Exception as e:
            error_message = str(e)
            logger.exception("Container execution failed")

        duration = time.monotonic() - start_time

        # Build result
        result = ContainerExecutionResult(
            success=error_message is None,
            output=result_text,
            error=error_message,
            input_tokens=total_input_tokens,
            output_tokens=total_output_tokens,
            duration_seconds=duration,
            estimated_cost_usd=estimated_cost,
            tool_count=tool_count,
        )

        # Emit session_completed or session_error
        if error_message:
            await self._store_event(
                {
                    "event_type": "session_error",
                    "session_id": session_id,
                    "error": error_message,
                    "timestamp": datetime.now(UTC).isoformat(),
                },
                execution_id,
                phase_id,
            )
            yield ContainerFailed(
                error=error_message,
                partial_result=result,
            )
        else:
            await self._store_event(
                {
                    "event_type": "session_completed",
                    "session_id": session_id,
                    "input_tokens": total_input_tokens,
                    "output_tokens": total_output_tokens,
                    "duration_seconds": duration,
                    "tool_count": tool_count,
                    "timestamp": datetime.now(UTC).isoformat(),
                },
                execution_id,
                phase_id,
            )
            yield ContainerCompleted(result=result)

    def _build_command(
        self,
        task: str,
        config: ContainerExecutionConfig,
    ) -> list[str]:
        """Build the claude CLI command."""
        cmd = [
            self._claude_command,
            "-p",  # Prompt mode
            task,
            "--output-format",
            "stream-json",  # Stream JSON for real-time events
        ]

        # Permission mode
        if config.permission_mode == "bypassPermissions":
            cmd.append("--dangerously-skip-permissions")

        # Max turns
        cmd.extend(["--max-turns", str(config.max_turns)])

        # Allowed tools
        if config.allowed_tools:
            cmd.extend(["--allowedTools", ",".join(config.allowed_tools)])

        return cmd

    def _parse_line(self, line: str) -> dict[str, Any] | None:
        """Parse a stdout line as JSON.

        Returns None for non-JSON lines.
        """
        line = line.strip()
        if not line:
            return None

        try:
            data = json.loads(line)
            if isinstance(data, dict):
                return data
            return None
        except json.JSONDecodeError:
            # Not JSON - might be debug output
            logger.debug("Non-JSON line: %s", line[:100])
            return None

    async def _store_event(
        self,
        event: dict[str, Any],
        execution_id: str | None,
        phase_id: str | None,
    ) -> None:
        """Store an event in the buffer."""
        if self._buffer is None:
            return

        await self._buffer.add(
            event,
            execution_id=execution_id,
            phase_id=phase_id,
        )


# Factory functions
_runner: ContainerAgentRunner | None = None


async def get_container_runner() -> ContainerAgentRunner:
    """Get a singleton ContainerAgentRunner with event buffering enabled.

    This factory:
    1. Initializes the AgentEventStore (TimescaleDB connection)
    2. Creates and starts an EventBuffer for batch inserts
    3. Creates a ContainerAgentRunner wired to the buffer

    Returns:
        Ready-to-use ContainerAgentRunner

    Example:
        from aef_adapters.agents import get_container_runner

        runner = await get_container_runner()

        async for event in runner.execute(
            task="Create hello.py",
            workspace=managed_workspace,
            session_id="session-123",
        ):
            print(event)
    """
    global _runner

    if _runner is None:
        from aef_adapters.events import get_event_buffer

        buffer = await get_event_buffer()
        _runner = ContainerAgentRunner(event_buffer=buffer)

    return _runner


def reset_container_runner() -> None:
    """Reset the singleton runner (for testing)."""
    global _runner
    _runner = None
