# mypy: ignore-errors
# Note: This file is deprecated and will be removed in PR #69.
# Type errors are suppressed to unblock the preceding PR.
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

from agentic_isolation import EventParser, EventType, ObservabilityEvent, SessionSummary

from aef_shared.events import (
    SESSION_ERROR,
    SESSION_STARTED,
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
                # Parse with EventParser - produces clean ObservabilityEvents
                # parse_line returns a list since one Claude event may produce multiple
                # observability events (e.g., assistant with tool_use produces TOKEN_USAGE + TOOL_STARTED)
                obs_events = parser.parse_line(line)

                # Also parse raw for hook event fallback (some events not in Claude CLI format)
                raw_event = self._parse_line(line)

                # If EventParser didn't produce events, fall back to hook event handling
                if not obs_events:
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
                    # Create a synthetic list with None to use raw_event data below
                    obs_events = [None]

                # Process each event from the parser (or the single hook event)
                for obs_event in obs_events:
                    # Get event type from obs_event or raw_event
                    if obs_event is not None:
                        event_type = obs_event.event_type
                        # Store each EventParser event directly - this is the authoritative storage
                        # EXCEPT session_completed: we store session_summary instead (richer data)
                        if event_type != EventType.SESSION_COMPLETED:
                            await self._store_observability_event(obs_event, execution_id, phase_id)
                    # else: event_type was set above from hook_type_map

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

                        # ADR-037: Detect Task tool as subagent start (for hook fallback)
                        # Note: EventParser produces SUBAGENT_STARTED events which are stored
                        # via _store_observability_event(). This block yields UI events for
                        # hook event fallback only (when obs_event is None).
                        if tool_name == "Task" and tool_use_id and obs_event is None:
                            agent_name = "unknown"
                            if isinstance(tool_input, dict):
                                agent_name = str(
                                    tool_input.get(
                                        "subagent_type",
                                        tool_input.get("description", "unknown"),
                                    )
                                )[:50]
                            active_subagents[tool_use_id] = (agent_name, datetime.now(UTC))

                            yield ContainerSubagentStarted(
                                agent_name=agent_name,
                                subagent_tool_use_id=tool_use_id,
                            )
                            logger.info(
                                "Subagent started (hook): %s (id=%s)", agent_name, tool_use_id
                            )

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
                        # Note: EventParser produces SUBAGENT_STOPPED events which are stored
                        # via _store_observability_event(). This block yields UI events for
                        # hook event fallback only.
                        if tool_name == "Task" and tool_use_id in active_subagents:
                            agent_name, started_at = active_subagents.pop(tool_use_id)
                            duration_ms = int(
                                (datetime.now(UTC) - started_at).total_seconds() * 1000
                            )

                            yield ContainerSubagentStopped(
                                agent_name=agent_name,
                                subagent_tool_use_id=tool_use_id,
                                duration_ms=duration_ms,
                                tools_used={},  # Tool attribution handled by EventParser
                                success=success,
                            )
                            logger.info(
                                "Subagent stopped (hook): %s (id=%s, duration=%dms)",
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

                    elif event_type == EventType.TOKEN_USAGE:
                        # Token usage events from assistant messages
                        if obs_event is not None and obs_event.tokens:
                            input_tokens = obs_event.tokens.input_tokens
                            output_tokens = obs_event.tokens.output_tokens
                            cache_creation = obs_event.tokens.cache_creation_tokens
                            cache_read = obs_event.tokens.cache_read_tokens
                            total_input_tokens = input_tokens  # Update cumulative (context window)
                            total_output_tokens += output_tokens
                            logger.debug(
                                "Token usage: input=%d, output=%d, cache_create=%d, cache_read=%d",
                                input_tokens,
                                output_tokens,
                                cache_creation,
                                cache_read,
                            )
                            # Note: Event already stored via _store_observability_event() above

                    # ADR-037: Subagent lifecycle events (detected by EventParser)
                    # Note: Events already stored via _store_observability_event() above
                    elif event_type == EventType.SUBAGENT_STARTED:
                        agent_name = obs_event.agent_name or "unknown"
                        tool_use_id = obs_event.subagent_tool_use_id or ""

                        yield ContainerSubagentStarted(
                            agent_name=agent_name,
                            subagent_tool_use_id=tool_use_id,
                        )
                        logger.info(
                            "Subagent started: %s (id=%s)",
                            agent_name,
                            tool_use_id,
                        )

                    elif event_type == EventType.SUBAGENT_STOPPED:
                        agent_name = obs_event.agent_name or "unknown"
                        tool_use_id = obs_event.subagent_tool_use_id or ""
                        duration_ms = obs_event.duration_ms
                        success = obs_event.success if obs_event.success is not None else True
                        tools_used = obs_event.tools_used or {}

                        yield ContainerSubagentStopped(
                            agent_name=agent_name,
                            subagent_tool_use_id=tool_use_id,
                            duration_ms=duration_ms,
                            tools_used=tools_used,
                            success=success,
                        )
                        logger.info(
                            "Subagent stopped: %s (id=%s, duration=%sms)",
                            agent_name,
                            tool_use_id,
                            duration_ms,
                        )

                    # Hook events and other types - just log
                    else:
                        logger.debug("Event: %s", event_type)

        except Exception as e:
            error_message = str(e)
            logger.exception("Container execution failed")

        duration = time.monotonic() - start_time

        # Get SessionSummary from EventParser for accurate cumulative totals
        # This has accurate values from Claude CLI result event
        summary = parser.get_summary()

        # Use summary totals (more accurate than our manual tracking)
        final_input_tokens = summary.total_input_tokens or total_input_tokens
        final_output_tokens = summary.total_output_tokens or total_output_tokens
        final_tool_count = summary.total_tool_calls or tool_count
        final_cost = (
            Decimal(str(summary.total_cost_usd))
            if summary.total_cost_usd is not None
            else estimated_cost
        )

        # Build result using summary totals
        result = ContainerExecutionResult(
            success=error_message is None,
            output=result_text,
            error=error_message,
            input_tokens=final_input_tokens,
            output_tokens=final_output_tokens,
            duration_seconds=duration,
            estimated_cost_usd=final_cost,
            tool_count=final_tool_count,
        )

        # Emit session_completed or session_error
        # Note: SESSION_COMPLETED event is already stored via _store_observability_event()
        # when EventParser produced it. We only store session_error for failure cases.
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
            # Store summary with accurate cumulative totals
            # This supplements the individual events with aggregated data
            await self._store_session_summary(summary, session_id, execution_id, phase_id)
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

    async def _store_observability_event(
        self,
        event: ObservabilityEvent,
        execution_id: str | None,
        phase_id: str | None,
    ) -> None:
        """Store an ObservabilityEvent from EventParser.

        This is the preferred way to store events - uses the clean
        ObservabilityEvent interface from agentic_isolation which
        normalizes all Claude CLI events.
        """
        if self._buffer is None:
            return

        # Convert to dict using ObservabilityEvent's to_dict()
        event_dict = event.to_dict()

        await self._buffer.add(
            event_dict,
            execution_id=execution_id,
            phase_id=phase_id,
        )

    async def _store_session_summary(
        self,
        summary: SessionSummary,
        session_id: str,
        execution_id: str | None,
        phase_id: str | None,
    ) -> None:
        """Store SessionSummary with accurate cumulative totals.

        Design Decision: We store this instead of EventParser's session_completed
        event because:
        1. SessionSummary has richer data (tokens, cost, tool counts, subagent metrics)
        2. Having one "session ended" event is cleaner than two overlapping events
        3. Projections only need to listen to session_summary for complete metrics

        The session_completed from EventParser is intentionally skipped in the
        execute() loop to avoid duplication - see the event_type != SESSION_COMPLETED check.
        """
        if self._buffer is None:
            return

        # Store as session_summary with aggregated data
        # This provides cumulative totals that projections can use
        await self._buffer.add(
            {
                "event_type": "session_summary",
                "session_id": session_id,
                "timestamp": datetime.now(UTC).isoformat(),
                "data": {
                    "total_input_tokens": summary.total_input_tokens,
                    "total_output_tokens": summary.total_output_tokens,
                    "total_cost_usd": summary.total_cost_usd,
                    "duration_ms": summary.duration_ms,
                    "num_turns": summary.num_turns,
                    "tool_count": summary.total_tool_calls,
                    "tool_calls": summary.tool_calls,
                    "subagent_count": summary.subagent_count,
                    "subagent_names": summary.subagent_names,
                    "success": summary.success,
                    "error_message": summary.error_message,
                },
            },
            execution_id=execution_id,
            phase_id=phase_id,
        )

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
