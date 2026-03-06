"""Event stream processor for workflow execution.

Processes Claude CLI JSONL output stream, dispatching events to
TokenAccumulator, SubagentTracker, and observability writer.

Extracted from WorkflowExecutionEngine._execute_phase_in_container().
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol

# Any: dict[str, Any] used for JSON data from json.loads() (system boundary — external CLI JSONL)
from agentic_events import enrich_event, parse_jsonl_line
from agentic_events.types import ClaudeToolName, EventType

from syn_domain.contexts.agent_sessions.domain.events.agent_observation import (
    ObservationType,
)
from syn_shared.events import VALID_EVENT_TYPES

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from syn_adapters.control import ExecutionController
    from syn_domain.contexts.orchestration.slices.execute_workflow.SubagentTracker import (
        SubagentTracker,
    )
    from syn_domain.contexts.orchestration.slices.execute_workflow.TokenAccumulator import (
        TokenAccumulator,
    )

logger = logging.getLogger(__name__)


class InterruptibleWorkspace(Protocol):
    """Protocol for workspace interrupt capability needed during stream processing."""

    async def interrupt(self) -> bool: ...


class ObservabilityRecorder(Protocol):
    """Protocol for recording observations to the observability backend."""

    async def record_observation(
        self,
        session_id: str,
        observation_type: ObservationType | str,
        data: dict[str, Any],
        execution_id: str | None = None,
        phase_id: str | None = None,
        workspace_id: str | None = None,
    ) -> None: ...


@dataclass(frozen=True)
class StreamResult:
    """Result of processing the event stream."""

    line_count: int
    interrupt_requested: bool
    interrupt_reason: str | None
    agent_task_result: dict[str, Any] | None
    conversation_lines: list[str] = field(default_factory=list)


class EventStreamProcessor:
    """Processes Claude CLI JSONL event stream.

    Dispatches events to TokenAccumulator and SubagentTracker,
    records observations, and accumulates conversation lines.
    """

    def __init__(
        self,
        tokens: TokenAccumulator,
        subagents: SubagentTracker,
        observability: ObservabilityRecorder | None,
        controller: ExecutionController | None,
        execution_id: str,
        phase_id: str,
        session_id: str,
        workspace_id: str | None,
        agent_model: str,
    ) -> None:
        self._tokens = tokens
        self._subagents = subagents
        self._observability = observability
        self._controller = controller
        self._execution_id = execution_id
        self._phase_id = phase_id
        self._session_id = session_id
        self._workspace_id = workspace_id
        self._agent_model = agent_model

    async def process_stream(
        self,
        stream: AsyncIterator[str],
        workspace: InterruptibleWorkspace,
    ) -> StreamResult:
        """Process the JSONL event stream from Claude CLI.

        Args:
            stream: Async iterator of JSONL lines from workspace.stream()
            workspace: Workspace instance (for interrupt())

        Returns:
            StreamResult with accumulated state
        """
        conversation_lines: list[str] = []
        line_count = 0
        interrupt_requested = False
        interrupt_reason: str | None = None
        agent_task_result: dict[str, Any] | None = None
        # Dedup set: same hook event appears as both raw stderr and
        # inside a hook_response envelope (stderr=STDOUT in container).
        seen_hook_fingerprints: set[tuple[str, ...]] = set()

        async for line in stream:
            line_count += 1
            logger.debug("Received line %d: %s", line_count, line[:100])

            # Poll for CANCEL signal every 10 lines
            if line_count % 10 == 0 and self._controller is not None:
                from syn_adapters.control.commands import ControlSignalType

                signal = await self._controller.check_signal(self._execution_id)
                if signal and signal.signal_type == ControlSignalType.CANCEL:
                    logger.info(
                        "CANCEL signal received for execution %s at line %d — sending SIGINT",
                        self._execution_id,
                        line_count,
                    )
                    interrupt_requested = True
                    interrupt_reason = signal.reason
                    await workspace.interrupt()
                    break

            # Collect line for conversation storage (ADR-035)
            if line.strip():
                conversation_lines.append(line)

            # Parse hook events from the stream
            hook_events = self._parse_hook_events(line)

            for hook_event in hook_events:
                # Deduplicate: same event can appear as raw stderr AND inside
                # hook_response envelope, or from multiple plugins.
                evt_type = hook_event.get("event_type", "")
                evt_sid = hook_event.get("session_id", "")
                evt_ctx = hook_event.get("context") or {}
                evt_tuid = evt_ctx.get("tool_use_id", "")
                if evt_tuid:
                    fp: tuple[str, ...] = (
                        evt_type,
                        evt_sid,
                        str(hook_event.get("timestamp", "")),
                        evt_tuid,
                    )
                else:
                    fp = (evt_type, evt_sid)
                if fp in seen_hook_fingerprints:
                    logger.debug("Skipping duplicate hook event: %s", fp[0])
                    continue
                seen_hook_fingerprints.add(fp)

                await self._process_hook_event(hook_event)

            # Skip native CLI event processing if we handled hook events
            if hook_events:
                continue

            # Fall back to Claude CLI native events
            task_result = await self._process_cli_event(line)
            if task_result is not None:
                agent_task_result = task_result

        logger.info(
            "Agent runner streaming complete: %d lines, %d input tokens, %d output tokens",
            line_count,
            self._tokens.input_tokens,
            self._tokens.output_tokens,
        )

        return StreamResult(
            line_count=line_count,
            interrupt_requested=interrupt_requested,
            interrupt_reason=interrupt_reason,
            agent_task_result=agent_task_result,
            conversation_lines=conversation_lines,
        )

    def _parse_hook_events(self, line: str) -> list[dict[str, Any]]:
        """Parse hook events from a stream line.

        Two sources:
        - SOURCE A: Standalone JSONL from Claude Code hooks
        - SOURCE B: hook_response system events with embedded JSONL
        """
        hook_events: list[dict[str, Any]] = []

        standalone = parse_jsonl_line(line)
        if standalone:
            hook_events.append(standalone)
        else:
            try:
                parsed = json.loads(line)
                line_type = parsed.get("type", "")
                line_subtype = parsed.get("subtype", "")

                if line_type == "system":
                    logger.info(
                        "System event: subtype=%s keys=%s",
                        line_subtype,
                        list(parsed.keys()),
                    )

                if line_type == "system" and line_subtype == "hook_response":
                    hook_name = parsed.get("hook_name", "?")
                    hook_event = parsed.get("hook_event", "?")
                    seen: set[str] = set()

                    for channel in ("output", "stdout", "stderr"):
                        channel_text = parsed.get(channel, "")
                        logger.info(
                            "hook_response hook=%s event=%s channel=%s len=%d content=%r",
                            hook_name,
                            hook_event,
                            channel,
                            len(channel_text),
                            channel_text[:300],
                        )
                        for hook_line in channel_text.splitlines():
                            hook_line = hook_line.strip()
                            if hook_line and hook_line not in seen:
                                evt = parse_jsonl_line(hook_line)
                                if evt:
                                    seen.add(hook_line)
                                    hook_events.append(evt)
                                else:
                                    logger.info(
                                        "hook_response line not a hook event: %r",
                                        hook_line[:200],
                                    )
            except (json.JSONDecodeError, AttributeError):
                pass

        return hook_events

    async def _process_hook_event(self, hook_event: dict[str, Any]) -> None:
        """Process a single hook event: validate, enrich, record, track subagents."""
        event_type = hook_event.get("event_type")
        if event_type not in VALID_EVENT_TYPES:
            logger.warning(
                "Unknown event_type from hook: %s — "
                "add it to syn_shared.events or check for a producer/consumer mismatch",
                event_type,
            )

        enriched = enrich_event(
            hook_event,
            execution_id=self._execution_id,
            phase_id=self._phase_id,
        )
        logger.debug("Hook event: %s", enriched.get("event_type"))

        # Store via observability writer
        if self._observability is not None:
            hook_data = {
                **(enriched.get("context") or {}),
                **(enriched.get("metadata") or {}),
            }
            await self._observability.record_observation(
                session_id=self._session_id,
                observation_type=enriched.get("event_type", "unknown"),
                data=hook_data,
                execution_id=self._execution_id,
                phase_id=self._phase_id,
                workspace_id=self._workspace_id,
            )

        # ADR-037: Detect subagent lifecycle from Task tool events.
        # Hook events use "event_type" (not "type") with values from
        # agentic_events.types.EventType (e.g. "tool_execution_started").
        hook_event_type = hook_event.get("event_type", "")
        ctx_data = enriched.get("context", {})
        tool_name = ctx_data.get("tool_name", "")
        tool_use_id = ctx_data.get("tool_use_id", "")

        if (
            tool_name in (ClaudeToolName.SUBAGENT, ClaudeToolName.SUBAGENT_LEGACY)
            and tool_use_id
        ):
            if hook_event_type == EventType.TOOL_EXECUTION_STARTED:
                input_preview = ctx_data.get("input_preview", "")
                event = self._subagents.on_task_started_from_hook(tool_use_id, input_preview)
                if self._observability is not None:
                    await self._observability.record_observation(
                        session_id=self._session_id,
                        observation_type=ObservationType.SUBAGENT_STARTED,
                        data={
                            "agent_name": event.agent_name,
                            "subagent_tool_use_id": tool_use_id,
                        },
                        execution_id=self._execution_id,
                        phase_id=self._phase_id,
                        workspace_id=self._workspace_id,
                    )
                    logger.info(
                        "Subagent started: %s (id=%s)",
                        event.agent_name,
                        tool_use_id,
                    )

            elif hook_event_type == EventType.TOOL_EXECUTION_COMPLETED:
                success = ctx_data.get("success", True)
                stopped_event = self._subagents.on_task_completed(tool_use_id, success=success)
                if stopped_event and self._observability is not None:
                    await self._observability.record_observation(
                        session_id=self._session_id,
                        observation_type=ObservationType.SUBAGENT_STOPPED,
                        data={
                            "agent_name": stopped_event.agent_name,
                            "subagent_tool_use_id": tool_use_id,
                            "duration_ms": stopped_event.duration_ms,
                            "success": stopped_event.success,
                            "tools_used": stopped_event.tools_used,
                        },
                        execution_id=self._execution_id,
                        phase_id=self._phase_id,
                        workspace_id=self._workspace_id,
                    )
                    logger.info(
                        "Subagent stopped: %s (id=%s, duration=%dms, tools=%s)",
                        stopped_event.agent_name,
                        tool_use_id,
                        stopped_event.duration_ms or 0,
                        stopped_event.tools_used,
                    )

    async def _process_cli_event(self, line: str) -> dict[str, Any] | None:
        """Process a Claude CLI native event. Returns task result if found."""
        try:
            cli_event = json.loads(line)
        except json.JSONDecodeError:
            logger.debug("Non-JSON line: %s", line[:50])
            return None

        cli_type = cli_event.get("type", "")
        logger.debug("CLI event type: %s", cli_type)

        task_result: dict[str, Any] | None = None

        if cli_type == "result":
            task_result = await self._handle_result_event(cli_event)

        if cli_type == "assistant":
            await self._handle_assistant_event(cli_event)

        if cli_type == "user":
            await self._handle_user_event(cli_event)

        if cli_type == "system":
            logger.debug("CLI message: %s", cli_type)

        return task_result

    async def _handle_result_event(self, cli_event: dict[str, Any]) -> dict[str, Any] | None:
        """Handle a result event — extract task result and token usage."""
        task_result: dict[str, Any] | None = None

        # Parse structured task result
        result_text = cli_event.get("result", "")
        if result_text and "TASK_RESULT:" in result_text:
            try:
                marker = "TASK_RESULT:"
                idx = result_text.rfind(marker)
                raw = result_text[idx + len(marker) :].strip()
                brace_end = raw.find("}")
                if brace_end >= 0:
                    raw = raw[: brace_end + 1]
                parsed_result: dict[str, Any] = json.loads(raw)
                task_result = parsed_result
                logger.info(
                    "Agent task result: success=%s comments=%s",
                    parsed_result.get("success"),
                    str(parsed_result.get("comments", ""))[:100],
                )
            except (json.JSONDecodeError, ValueError):
                logger.debug("Could not parse TASK_RESULT block")

        # Extract token usage
        usage = cli_event.get("usage", {})
        input_tokens = usage.get("input_tokens", 0)
        output_tokens = usage.get("output_tokens", 0)

        if input_tokens > 0 or output_tokens > 0:
            self._tokens.record(input_tokens, output_tokens)

            if self._observability is not None:
                cache_creation = usage.get("cache_creation_input_tokens", 0)
                cache_read = usage.get("cache_read_input_tokens", 0)
                await self._observability.record_observation(
                    session_id=self._session_id,
                    observation_type=ObservationType.TOKEN_USAGE,
                    data={
                        "input_tokens": input_tokens,
                        "output_tokens": output_tokens,
                        "cache_creation_tokens": cache_creation,
                        "cache_read_tokens": cache_read,
                        "model": self._agent_model,
                    },
                    execution_id=self._execution_id,
                    phase_id=self._phase_id,
                    workspace_id=self._workspace_id,
                )
                logger.info(
                    "Result token usage: %d in, %d out",
                    input_tokens,
                    output_tokens,
                )

        return task_result

    async def _handle_assistant_event(self, cli_event: dict[str, Any]) -> None:
        """Handle assistant event — extract per-turn tokens and tool_use."""
        message = cli_event.get("message", {})
        content = message.get("content", [])

        # Extract per-turn token usage
        usage = message.get("usage", {})
        if usage:
            input_tokens = usage.get("input_tokens", 0)
            output_tokens = usage.get("output_tokens", 0)

            if input_tokens > 0 or output_tokens > 0:
                self._tokens.record(input_tokens, output_tokens)

                if self._observability is not None:
                    cache_creation = usage.get("cache_creation_input_tokens", 0)
                    cache_read = usage.get("cache_read_input_tokens", 0)
                    await self._observability.record_observation(
                        session_id=self._session_id,
                        observation_type=ObservationType.TOKEN_USAGE,
                        data={
                            "input_tokens": input_tokens,
                            "output_tokens": output_tokens,
                            "cache_creation_tokens": cache_creation,
                            "cache_read_tokens": cache_read,
                            "model": self._agent_model,
                        },
                        execution_id=self._execution_id,
                        phase_id=self._phase_id,
                        workspace_id=self._workspace_id,
                    )
                    logger.info(
                        "Per-turn token usage: %d in, %d out (cache: %d read, %d create)",
                        input_tokens,
                        output_tokens,
                        cache_read,
                        cache_creation,
                    )

        # Process tool_use items
        for item in content:
            if isinstance(item, dict) and item.get("type") == "tool_use":
                await self._handle_tool_use(item)

    async def _handle_tool_use(self, item: dict[str, Any]) -> None:
        """Handle a tool_use content block from an assistant message."""
        tool_name = item.get("name", "unknown")
        tool_use_id = item.get("id", "unknown")
        tool_input = item.get("input", {})
        if isinstance(tool_input, str):
            try:
                tool_input = json.loads(tool_input)
            except (json.JSONDecodeError, ValueError):
                tool_input = {}

        # Cache tool_name for enriching tool_result events
        self._subagents.register_tool_use(tool_use_id, tool_name)

        if self._observability is not None:
            await self._observability.record_observation(
                session_id=self._session_id,
                observation_type=ObservationType.TOOL_EXECUTION_STARTED,
                data={
                    "tool_name": tool_name,
                    "tool_use_id": tool_use_id,
                    "input_preview": json.dumps(tool_input)[:500],
                },
                execution_id=self._execution_id,
                phase_id=self._phase_id,
                workspace_id=self._workspace_id,
            )
            logger.debug("Tool started: %s", tool_name)

        # ADR-037: Detect Task/Agent tool as subagent start (raw CLI format)
        if (
            tool_name in (ClaudeToolName.SUBAGENT, ClaudeToolName.SUBAGENT_LEGACY)
            and tool_use_id
        ):
            event = self._subagents.on_task_started(tool_use_id, tool_input)
            if self._observability is not None:
                await self._observability.record_observation(
                    session_id=self._session_id,
                    observation_type=ObservationType.SUBAGENT_STARTED,
                    data={
                        "agent_name": event.agent_name,
                        "subagent_tool_use_id": tool_use_id,
                    },
                    execution_id=self._execution_id,
                    phase_id=self._phase_id,
                    workspace_id=self._workspace_id,
                )
                logger.info(
                    "Subagent started (CLI): %s (id=%s)",
                    event.agent_name,
                    tool_use_id,
                )

    async def _handle_user_event(self, cli_event: dict[str, Any]) -> None:
        """Handle user event — process tool results."""
        message = cli_event.get("message", {})
        content = message.get("content", [])

        for item in content:
            if isinstance(item, dict) and item.get("type") == "tool_result":
                await self._handle_tool_result(item)

    async def _handle_tool_result(self, item: dict[str, Any]) -> None:
        """Handle a tool_result content block from a user message."""
        tool_use_id = item.get("tool_use_id", "unknown")
        is_error = item.get("is_error", False)

        # Extract tool output content
        tool_content = item.get("content", "")
        if isinstance(tool_content, list):
            tool_content = " ".join(
                str(c.get("text", c) if isinstance(c, dict) else c) for c in tool_content
            )
        output_preview = str(tool_content)[:500] if tool_content else None
        tool_name = self._subagents.resolve_tool_name(tool_use_id)

        # Scan tool output for embedded git hook JSONL (ADR-043)
        if tool_content and self._observability is not None:
            for tl in str(tool_content).splitlines():
                tl = tl.strip()
                if not tl:
                    continue
                embedded = parse_jsonl_line(tl)
                if not embedded:
                    continue
                et = embedded.get("event_type")
                if et not in VALID_EVENT_TYPES:
                    logger.debug("Unknown event_type in tool output: %s", et)
                    continue
                enriched = enrich_event(
                    embedded,
                    execution_id=self._execution_id,
                    phase_id=self._phase_id,
                )
                hd = {
                    **(enriched.get("context") or {}),
                    **(enriched.get("metadata") or {}),
                }
                await self._observability.record_observation(
                    session_id=self._session_id,
                    observation_type=et,
                    data=hd,
                    execution_id=self._execution_id,
                    phase_id=self._phase_id,
                    workspace_id=self._workspace_id,
                )
                logger.info(
                    "Git hook event from tool output: %s (tool=%s)",
                    et,
                    tool_name,
                )

        # Record tool completion
        if self._observability is not None:
            await self._observability.record_observation(
                session_id=self._session_id,
                observation_type=ObservationType.TOOL_EXECUTION_COMPLETED,
                data={
                    "tool_name": tool_name,
                    "tool_use_id": tool_use_id,
                    "success": not is_error,
                    "output_preview": output_preview,
                },
                execution_id=self._execution_id,
                phase_id=self._phase_id,
                workspace_id=self._workspace_id,
            )
            logger.debug(
                "Tool completed: %s (%s) success=%s",
                tool_use_id,
                tool_name,
                not is_error,
            )

        # ADR-037: Detect Task/Agent tool completion as subagent stop (raw CLI format)
        _is_subagent = tool_name in (ClaudeToolName.SUBAGENT, ClaudeToolName.SUBAGENT_LEGACY)
        if _is_subagent:
            event = self._subagents.on_task_completed(tool_use_id, success=not is_error)
            if event and self._observability is not None:
                await self._observability.record_observation(
                    session_id=self._session_id,
                    observation_type=ObservationType.SUBAGENT_STOPPED,
                    data={
                        "agent_name": event.agent_name,
                        "subagent_tool_use_id": tool_use_id,
                        "duration_ms": event.duration_ms,
                        "success": event.success,
                        "tools_used": event.tools_used,
                    },
                    execution_id=self._execution_id,
                    phase_id=self._phase_id,
                    workspace_id=self._workspace_id,
                )
                logger.info(
                    "Subagent stopped (CLI): %s (id=%s, duration=%dms, tools=%s)",
                    event.agent_name,
                    tool_use_id,
                    event.duration_ms or 0,
                    event.tools_used,
                )
        elif not _is_subagent:
            # Attribute non-subagent tool to the most recently started subagent
            self._subagents.attribute_tool(tool_name)
