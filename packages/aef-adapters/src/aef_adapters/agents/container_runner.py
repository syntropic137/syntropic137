"""Container Agent Runner - Execute agents inside Docker and capture JSONL events.

ADR-029: Simplified Event System - This bridges containerized execution with
the new JSONL event system for storage in TimescaleDB.

ADR-037: Uses EventParser from agentic-primitives for:
- Tool name enrichment (tool_use_id → tool_name mapping)
- Subagent lifecycle tracking (Task tool → subagent_started/stopped)
- Normalized ObservabilityEvent output

This module provides an agent runner that:
1. Runs the claude CLI inside a Docker container
2. Streams stdout line by line
3. Parses JSONL via EventParser (tested in agentic-primitives)
4. Translates ObservabilityEvents → ContainerEvents (domain boundary)
5. Stores events in AgentEventStore via EventBuffer

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

from agentic_isolation import EventParser, EventType

from aef_shared.events import (
    SESSION_COMPLETED,
    SESSION_ERROR,
    SESSION_STARTED,
    SUBAGENT_STARTED,
    SUBAGENT_STOPPED,
)

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


# NOTE: Tool name enrichment is now handled by EventParser from agentic-primitives
# The duplicate _extract_tool_uses and _enrich_tool_result functions were removed
# as part of ADR-037 refactoring to use the shared EventParser.


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


@dataclass
class ContainerSubagentStarted:
    """Subagent spawned via Task tool.

    Emitted when Claude uses the Task tool to spawn a nested agent.
    The subagent_tool_use_id is the correlation ID for tracking.
    """

    agent_name: str
    subagent_tool_use_id: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class ContainerSubagentStopped:
    """Subagent completed execution.

    Emitted when the Task tool returns with the subagent result.
    """

    agent_name: str
    subagent_tool_use_id: str
    duration_ms: int | None = None
    tools_used: dict[str, int] = field(default_factory=dict)
    success: bool = True


# Type alias for execution events
ContainerEvent = (
    ContainerToolStarted
    | ContainerToolCompleted
    | ContainerTurnCompleted
    | ContainerOutput
    | ContainerCompleted
    | ContainerFailed
    | ContainerSubagentStarted
    | ContainerSubagentStopped
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

        # ADR-037: Use EventParser from agentic-primitives for:
        # - Tool name enrichment (tool_use_id → tool_name)
        # - Subagent lifecycle tracking (Task tool detection)
        # This is the clean translation boundary between isolation and domain
        parser = EventParser(session_id)

        # Track active subagents for hook-style events (fallback)
        # EventParser handles raw Claude CLI format; this handles hook events
        active_subagents: dict[str, tuple[str, datetime]] = {}

        # Emit session_started event
        await self._store_event(
            {
                "event_type": SESSION_STARTED,
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
                # Parse raw event for storage
                raw_event = self._parse_line(line)
                if raw_event is None:
                    continue

                # Store raw event for persistence
                await self._store_event(
                    {**raw_event, "session_id": session_id},
                    execution_id,
                    phase_id,
                )

                # Try EventParser for raw Claude CLI format (handles assistant/user messages)
                obs_event = parser.parse_line(line)

                # Get event type from either EventParser result or raw event
                if obs_event is not None:
                    event_type = obs_event.event_type
                else:
                    # Fallback: handle hook events directly (tool_execution_started, etc.)
                    raw_type = raw_event.get("type") or raw_event.get("event_type", "")
                    # Map hook event types to EventType enum
                    hook_type_map = {
                        "tool_execution_started": EventType.TOOL_EXECUTION_STARTED,
                        "tool_execution_completed": EventType.TOOL_EXECUTION_COMPLETED,
                        "tool_use_started": EventType.TOOL_EXECUTION_STARTED,
                        "tool_use_completed": EventType.TOOL_EXECUTION_COMPLETED,
                        "turn_completed": EventType.TURN_COMPLETED,
                        "token_usage": EventType.TOKEN_USAGE,
                        "result": EventType.RESULT,
                        "error": EventType.ERROR,
                    }
                    event_type = hook_type_map.get(raw_type)
                    if event_type is None:
                        continue

                if event_type == EventType.TOOL_EXECUTION_STARTED:
                    # Get tool info from obs_event or raw_event
                    if obs_event is not None:
                        tool_name = obs_event.tool_name or "unknown"
                        tool_use_id = obs_event.tool_use_id or ""
                        tool_input = obs_event.tool_input
                    else:
                        tool_name = raw_event.get("tool_name", "unknown")
                        tool_use_id = raw_event.get("tool_use_id", "")
                        # Hook events have input_preview (JSON string) not tool_input (dict)
                        tool_input = raw_event.get("tool_input")
                        if tool_input is None and "input_preview" in raw_event:
                            try:
                                tool_input = json.loads(raw_event["input_preview"])
                            except (json.JSONDecodeError, TypeError):
                                tool_input = None

                    yield ContainerToolStarted(
                        tool_name=tool_name,
                        tool_input=tool_input,
                        tool_use_id=tool_use_id,
                    )

                    # ADR-037: Detect Task tool as subagent start
                    if tool_name == "Task" and tool_use_id:
                        agent_name = "unknown"
                        if isinstance(tool_input, dict):
                            agent_name = str(
                                tool_input.get(
                                    "subagent_type",
                                    tool_input.get("description", "unknown"),
                                )
                            )[:50]
                        active_subagents[tool_use_id] = (agent_name, datetime.now(UTC))

                        # Store subagent_started event
                        await self._store_event(
                            {
                                "event_type": SUBAGENT_STARTED,
                                "session_id": session_id,
                                "agent_name": agent_name,
                                "subagent_tool_use_id": tool_use_id,
                                "timestamp": datetime.now(UTC).isoformat(),
                            },
                            execution_id,
                            phase_id,
                        )

                        yield ContainerSubagentStarted(
                            agent_name=agent_name,
                            subagent_tool_use_id=tool_use_id,
                        )
                        logger.info("Subagent started: %s (id=%s)", agent_name, tool_use_id)

                elif event_type == EventType.TOOL_EXECUTION_COMPLETED:
                    tool_count += 1
                    # Get tool info from obs_event or raw_event
                    if obs_event is not None:
                        tool_name = obs_event.tool_name or "unknown"
                        tool_use_id = obs_event.tool_use_id or ""
                        success = obs_event.success if obs_event.success is not None else True
                        duration_ms = obs_event.duration_ms
                        error = obs_event.error
                    else:
                        tool_name = raw_event.get("tool_name", "unknown")
                        tool_use_id = raw_event.get("tool_use_id", "")
                        success = raw_event.get("success", True)
                        duration_ms = raw_event.get("duration_ms")
                        error = raw_event.get("error")

                    yield ContainerToolCompleted(
                        tool_name=tool_name,
                        tool_use_id=tool_use_id,
                        success=success,
                        duration_ms=duration_ms,
                        error=error,
                    )

                    # ADR-037: Detect Task tool completion as subagent stop (hook event fallback)
                    if tool_name == "Task" and tool_use_id in active_subagents:
                        agent_name, started_at = active_subagents.pop(tool_use_id)
                        duration_ms = int((datetime.now(UTC) - started_at).total_seconds() * 1000)

                        # Store subagent_stopped event
                        await self._store_event(
                            {
                                "event_type": SUBAGENT_STOPPED,
                                "session_id": session_id,
                                "agent_name": agent_name,
                                "subagent_tool_use_id": tool_use_id,
                                "duration_ms": duration_ms,
                                "success": success,
                                "timestamp": datetime.now(UTC).isoformat(),
                            },
                            execution_id,
                            phase_id,
                        )

                        yield ContainerSubagentStopped(
                            agent_name=agent_name,
                            subagent_tool_use_id=tool_use_id,
                            duration_ms=duration_ms,
                            tools_used={},  # Tool attribution handled by EventParser at parsing layer
                            success=success,
                        )
                        logger.info(
                            "Subagent stopped: %s (id=%s, duration=%dms)",
                            agent_name,
                            tool_use_id,
                            duration_ms,
                        )

                elif event_type == EventType.TURN_COMPLETED:
                    turn_number += 1
                    if obs_event is not None and obs_event.tokens:
                        input_tokens = obs_event.tokens.input_tokens
                        output_tokens = obs_event.tokens.output_tokens
                    else:
                        input_tokens = raw_event.get("input_tokens", 0)
                        output_tokens = raw_event.get("output_tokens", 0)
                    total_input_tokens += input_tokens
                    total_output_tokens += output_tokens

                    yield ContainerTurnCompleted(
                        turn_number=turn_number,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        cumulative_input_tokens=total_input_tokens,
                        cumulative_output_tokens=total_output_tokens,
                    )

                elif event_type == EventType.TEXT_OUTPUT:
                    if obs_event is not None:
                        content = obs_event.content or ""
                        is_partial = (
                            obs_event.is_partial if obs_event.is_partial is not None else False
                        )
                    else:
                        content = raw_event.get("content", "")
                        is_partial = raw_event.get("is_partial", False)
                    yield ContainerOutput(
                        content=content,
                        is_partial=is_partial,
                    )
                    if not is_partial:
                        result_text += content

                elif event_type == EventType.RESULT:
                    # Claude CLI final result message
                    if obs_event is not None:
                        result_text = obs_event.result or result_text
                        if obs_event.cost_usd is not None:
                            estimated_cost = Decimal(str(obs_event.cost_usd))
                        if obs_event.tokens:
                            total_input_tokens = obs_event.tokens.input_tokens
                            total_output_tokens = obs_event.tokens.output_tokens
                    else:
                        result_text = raw_event.get("result", result_text)
                        if "cost_usd" in raw_event:
                            estimated_cost = Decimal(str(raw_event["cost_usd"]))
                        if "input_tokens" in raw_event:
                            total_input_tokens = raw_event["input_tokens"]
                        if "output_tokens" in raw_event:
                            total_output_tokens = raw_event["output_tokens"]

                elif event_type == EventType.ERROR:
                    if obs_event is not None:
                        error_message = obs_event.error or "Unknown error"
                    else:
                        error_message = raw_event.get("error", "Unknown error")

                # ADR-037: Subagent lifecycle events (detected by EventParser)
                elif event_type == EventType.SUBAGENT_STARTED:
                    yield ContainerSubagentStarted(
                        agent_name=obs_event.agent_name or "unknown",
                        subagent_tool_use_id=obs_event.subagent_tool_use_id or "",
                    )
                    logger.info(
                        "Subagent started: %s (id=%s)",
                        obs_event.agent_name,
                        obs_event.subagent_tool_use_id,
                    )

                elif event_type == EventType.SUBAGENT_STOPPED:
                    yield ContainerSubagentStopped(
                        agent_name=obs_event.agent_name or "unknown",
                        subagent_tool_use_id=obs_event.subagent_tool_use_id or "",
                        duration_ms=obs_event.duration_ms,
                        tools_used={},  # TODO: Get from parser summary if needed
                        success=obs_event.success if obs_event.success is not None else True,
                    )
                    logger.info(
                        "Subagent stopped: %s (id=%s, duration=%sms)",
                        obs_event.agent_name,
                        obs_event.subagent_tool_use_id,
                        obs_event.duration_ms,
                    )

                # Hook events and other types - just log
                else:
                    logger.debug("Event: %s", event_type)

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
        # Note: session_error is a variant of session lifecycle, not in shared constants
        if error_message:
            await self._store_event(
                {
                    "event_type": SESSION_ERROR,
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
                    "event_type": SESSION_COMPLETED,
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
