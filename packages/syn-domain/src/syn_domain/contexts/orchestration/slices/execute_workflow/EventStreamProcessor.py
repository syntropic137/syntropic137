"""Event stream processor for workflow execution.

Processes Claude CLI JSONL output stream, dispatching events to
TokenAccumulator, SubagentTracker, and ObservabilityCollector.

Extracted from WorkflowExecutionEngine._execute_phase_in_container().
Refactored in ISS-196 to delegate telemetry to ObservabilityCollector (Lane 2).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol

# Any: dict[str, Any] used for JSON data from json.loads() (system boundary — external CLI JSONL)
from agentic_events import enrich_event, parse_jsonl_line
from agentic_events.types import ClaudeToolName, EventType

from syn_domain.contexts.orchestration.slices.execute_workflow.HookEventParser import (
    HookEventParser,
)
from syn_shared.events import VALID_EVENT_TYPES

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from syn_adapters.control import ExecutionController
    from syn_domain.contexts.agent_sessions.domain.events.agent_observation import (
        ObservationType,
    )
    from syn_domain.contexts.orchestration.slices.execute_workflow.ObservabilityCollector import (
        ObservabilityCollector,
    )
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
    delegates telemetry recording to ObservabilityCollector (Lane 2).
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
        collector: ObservabilityCollector | None = None,
    ) -> None:
        self._tokens = tokens
        self._subagents = subagents
        self._controller = controller
        self._execution_id = execution_id
        self._phase_id = phase_id
        self._session_id = session_id
        self._workspace_id = workspace_id
        self._agent_model = agent_model

        # ISS-196: Use collector if provided, else create one from raw writer
        if collector is not None:
            self._collector = collector
        else:
            from syn_domain.contexts.orchestration.slices.execute_workflow.ObservabilityCollector import (
                ObservabilityCollector as OC,
            )

            self._collector = OC(
                writer=observability,
                session_id=session_id,
                execution_id=execution_id,
                phase_id=phase_id,
                workspace_id=workspace_id,
                agent_model=agent_model,
            )

        # ISS-196: Collaborator for hook event parsing + dedup
        self._hook_parser = HookEventParser()

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

            # Parse hook events from the stream (parsing + dedup in HookEventParser)
            hook_events = self._hook_parser.parse(line)
            for hook_event in hook_events:
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

        # Lane 2: Record via collector
        await self._collector.record_hook_event(enriched)

        # ADR-037: Detect subagent lifecycle from Task tool events.
        hook_event_type = hook_event.get("event_type", "")
        ctx_data = enriched.get("context", {})
        tool_name = ctx_data.get("tool_name", "")
        tool_use_id = ctx_data.get("tool_use_id", "")

        # Attribute non-Task tool calls to the active subagent (if any)
        if (
            tool_name
            and tool_name not in (ClaudeToolName.SUBAGENT, ClaudeToolName.SUBAGENT_LEGACY)
            and self._subagents.has_active
        ):
            self._subagents.attribute_tool(tool_name)

        if tool_name in (ClaudeToolName.SUBAGENT, ClaudeToolName.SUBAGENT_LEGACY) and tool_use_id:
            if hook_event_type == EventType.TOOL_EXECUTION_STARTED:
                input_preview = ctx_data.get("input_preview", "")
                event = self._subagents.on_task_started_from_hook(tool_use_id, input_preview)
                await self._collector.record_subagent_started(event.agent_name, tool_use_id)

            elif hook_event_type == EventType.TOOL_EXECUTION_COMPLETED:
                success = ctx_data.get("success", True)
                stopped_event = self._subagents.on_task_completed(tool_use_id, success=success)
                if stopped_event:
                    await self._collector.record_subagent_stopped(
                        agent_name=stopped_event.agent_name,
                        tool_use_id=tool_use_id,
                        duration_ms=stopped_event.duration_ms,
                        success=stopped_event.success,
                        tools_used=stopped_event.tools_used,
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

            cache_creation = usage.get("cache_creation_input_tokens", 0)
            cache_read = usage.get("cache_read_input_tokens", 0)
            await self._collector.record_token_usage(
                input_tokens,
                output_tokens,
                cache_creation,
                cache_read,
            )
            logger.info("Result token usage: %d in, %d out", input_tokens, output_tokens)

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

                cache_creation = usage.get("cache_creation_input_tokens", 0)
                cache_read = usage.get("cache_read_input_tokens", 0)
                await self._collector.record_token_usage(
                    input_tokens,
                    output_tokens,
                    cache_creation,
                    cache_read,
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

        await self._collector.record_tool_started(
            tool_name=tool_name,
            tool_use_id=tool_use_id,
            input_preview=json.dumps(tool_input)[:500],
        )
        logger.debug("Tool started: %s", tool_name)

        # ADR-037: Detect Task/Agent tool as subagent start (raw CLI format)
        if tool_name in (ClaudeToolName.SUBAGENT, ClaudeToolName.SUBAGENT_LEGACY) and tool_use_id:
            event = self._subagents.on_task_started(tool_use_id, tool_input)
            await self._collector.record_subagent_started(event.agent_name, tool_use_id)

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
        if tool_content:
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
                await self._collector.record_embedded_event(et, enriched)
                logger.info(
                    "Git hook event from tool output: %s (tool=%s)",
                    et,
                    tool_name,
                )

        # Record tool completion
        await self._collector.record_tool_completed(
            tool_name=tool_name,
            tool_use_id=tool_use_id,
            success=not is_error,
            output_preview=output_preview,
        )
        logger.debug("Tool completed: %s (%s) success=%s", tool_use_id, tool_name, not is_error)

        # ADR-037: Detect Task/Agent tool completion as subagent stop (raw CLI format)
        _is_subagent = tool_name in (ClaudeToolName.SUBAGENT, ClaudeToolName.SUBAGENT_LEGACY)
        if _is_subagent:
            event = self._subagents.on_task_completed(tool_use_id, success=not is_error)
            if event:
                await self._collector.record_subagent_stopped(
                    agent_name=event.agent_name,
                    tool_use_id=tool_use_id,
                    duration_ms=event.duration_ms,
                    success=event.success,
                    tools_used=event.tools_used,
                )
        elif not _is_subagent:
            # Attribute non-subagent tool to the most recently started subagent
            self._subagents.attribute_tool(tool_name)
