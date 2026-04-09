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
from enum import Enum, auto
from typing import TYPE_CHECKING, Any, Protocol

# Any: dict[str, Any] used for JSON data from json.loads() (system boundary — external CLI JSONL)
from agentic_events.types import ClaudeToolName, EventType

from syn_domain.contexts.orchestration.slices.execute_workflow.CancelSignalPoller import (
    CancelSignalPoller,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.EmbeddedEventScanner import (
    EmbeddedEventScanner,
)
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


_MAX_ERROR_REASON_LEN = 200

# Well-known Anthropic API error types → human-readable labels
_API_ERROR_LABELS: dict[str, str] = {
    "overloaded_error": "API overloaded",
    "rate_limit_error": "Rate limited",
    "api_error": "API internal error",
    "authentication_error": "Authentication failed",
    "invalid_request_error": "Invalid request",
    "not_found_error": "Resource not found",
    "permission_error": "Permission denied",
}


def _http_code_from_prefix(prefix: str) -> str:
    """Return the first 3-digit token from a prefix like 'API Error: 529 '."""
    return next((w for w in prefix.split() if w.isdigit() and len(w) == 3), "")


def _format_anthropic_error(error_obj: dict[str, object], prefix: str) -> str:
    """Format a human-readable label from an Anthropic API error dict."""
    error_type = str(error_obj.get("type", ""))
    message = str(error_obj.get("message", ""))
    label = _API_ERROR_LABELS.get(error_type, error_type.replace("_", " "))
    http_code = _http_code_from_prefix(prefix)
    if http_code:
        return f"{label} (HTTP {http_code})"
    if message and message.lower() != label.lower():
        return f"{label}: {message}"
    return label


def _parse_json_error(text: str) -> str | None:
    """Try to parse an embedded JSON error body and return a label, or None."""
    brace_start = text.find("{")
    if brace_start < 0:
        return None
    prefix = text[:brace_start].strip()
    try:
        parsed = json.loads(text[brace_start:])
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(parsed, dict):
        return None
    error_obj = parsed.get("error")
    if isinstance(error_obj, dict):
        return _format_anthropic_error(error_obj, prefix)
    if isinstance(parsed.get("message"), str):
        return str(parsed["message"])[:_MAX_ERROR_REASON_LEN]
    return None


def _extract_error_reason(raw: str) -> str:
    """Extract a clean, human-readable error reason from CLI result text.

    The CLI result can contain raw JSON error bodies, stack traces, or plain
    text. This function extracts the most useful signal and returns a short,
    readable string suitable for display in the dashboard and CLI.

    Examples:
        >>> _extract_error_reason('API Error: 529 {"type":"error","error":{"type":"overloaded_error","message":"Overloaded"},...}')
        'API overloaded (HTTP 529)'
        >>> _extract_error_reason('Connection refused')
        'Connection refused'
    """
    text = raw.strip()
    if not text:
        return "Unknown error"
    json_label = _parse_json_error(text)
    if json_label is not None:
        return json_label
    if len(text) <= _MAX_ERROR_REASON_LEN:
        return text
    return text[:_MAX_ERROR_REASON_LEN].rsplit(" ", 1)[0] + "..."


@dataclass(frozen=True)
class StreamResult:
    """Result of processing the event stream."""

    line_count: int
    interrupt_requested: bool
    interrupt_reason: str | None
    agent_task_result: dict[str, Any] | None
    conversation_lines: list[str] = field(default_factory=list)
    # Authoritative totals from the CLI result event (ISS-217)
    total_cost_usd: float | None = None
    result_input_tokens: int = 0
    result_output_tokens: int = 0
    result_cache_creation: int = 0
    result_cache_read: int = 0
    duration_ms: int | None = None
    num_turns: int | None = None
    # Error reason extracted from CLI result event (e.g. "API Error: 529 Overloaded")
    error_reason: str | None = None


_SUBAGENT_TOOL_NAMES = frozenset({ClaudeToolName.SUBAGENT, ClaudeToolName.SUBAGENT_LEGACY})


class _LineAction(Enum):
    """Outcome of processing a single stream line."""

    CONTINUE = auto()
    BREAK = auto()


@dataclass
class _LineOutcome:
    action: _LineAction
    interrupt_reason: str | None = None
    task_result: dict[str, Any] | None = None


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
        self._execution_id = execution_id
        self._phase_id = phase_id
        self._session_id = session_id
        self._workspace_id = workspace_id
        self._agent_model = agent_model

        # ISS-217: Authoritative totals captured from the CLI result event
        self._result_cost_usd: float | None = None
        self._result_input_tokens: int = 0
        self._result_output_tokens: int = 0
        self._result_cache_creation: int = 0
        self._result_cache_read: int = 0
        self._result_duration_ms: int | None = None
        self._result_num_turns: int | None = None
        self._error_reason: str | None = None

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

        # Collaborators extracted for CC reduction (ISS-196)
        self._hook_parser = HookEventParser()
        self._embedded_scanner = EmbeddedEventScanner(
            collector=self._collector,
            execution_id=execution_id,
            phase_id=phase_id,
        )
        self._cancel_poller = CancelSignalPoller(
            controller=controller,
            execution_id=execution_id,
        )

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
        interrupt_reason: str | None = None
        agent_task_result: dict[str, Any] | None = None

        async for line in stream:
            line_count += 1
            outcome = await self._process_line(line, line_count, workspace)
            if line.strip():
                conversation_lines.append(line)
            if outcome.task_result is not None:
                agent_task_result = outcome.task_result
            if outcome.action is _LineAction.BREAK:
                interrupt_reason = outcome.interrupt_reason
                break

        logger.info(
            "Agent runner streaming complete: %d lines, cost=$%s (%d in, %d out)",
            line_count,
            self._result_cost_usd,
            self._result_input_tokens,
            self._result_output_tokens,
        )

        return StreamResult(
            line_count=line_count,
            interrupt_requested=interrupt_reason is not None,
            interrupt_reason=interrupt_reason,
            agent_task_result=agent_task_result,
            conversation_lines=conversation_lines,
            total_cost_usd=self._result_cost_usd,
            result_input_tokens=self._result_input_tokens,
            result_output_tokens=self._result_output_tokens,
            result_cache_creation=self._result_cache_creation,
            result_cache_read=self._result_cache_read,
            duration_ms=self._result_duration_ms,
            num_turns=self._result_num_turns,
            error_reason=self._error_reason,
        )

    async def _process_line(
        self,
        line: str,
        line_count: int,
        workspace: InterruptibleWorkspace,
    ) -> _LineOutcome:
        """Process a single stream line: cancel check, hook events, or CLI event."""
        logger.debug("Received line %d: %s", line_count, line[:100])

        poll = await self._cancel_poller.check(line_count)
        if poll.should_interrupt:
            await workspace.interrupt()
            return _LineOutcome(action=_LineAction.BREAK, interrupt_reason=poll.reason)

        hook_events = self._hook_parser.parse(line)
        if hook_events:
            for hook_event in hook_events:
                await self._process_hook_event(hook_event)
            return _LineOutcome(action=_LineAction.CONTINUE)

        task_result = await self._process_cli_event(line)
        return _LineOutcome(action=_LineAction.CONTINUE, task_result=task_result)

    async def _process_hook_event(self, hook_event: dict[str, Any]) -> None:
        """Process a single hook event: validate, enrich, record, track subagents."""
        from agentic_events import enrich_event

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

        # ADR-037: Track subagent lifecycle from hook events
        await self._track_subagent_from_hook(hook_event, enriched)

    async def _track_subagent_from_hook(
        self, hook_event: dict[str, Any], enriched: dict[str, Any]
    ) -> None:
        """ADR-037: Detect subagent lifecycle from Task tool hook events."""
        ctx_data = enriched.get("context", {})
        tool_name = ctx_data.get("tool_name", "")
        tool_use_id = ctx_data.get("tool_use_id", "")

        if tool_name not in _SUBAGENT_TOOL_NAMES:
            if tool_name and self._subagents.has_active:
                self._subagents.attribute_tool(tool_name)
            return

        if not tool_use_id:
            return

        hook_event_type = hook_event.get("event_type", "")
        if hook_event_type == EventType.TOOL_EXECUTION_STARTED:
            await self._on_hook_subagent_started(ctx_data, tool_use_id)
        elif hook_event_type == EventType.TOOL_EXECUTION_COMPLETED:
            await self._on_hook_subagent_completed(ctx_data, tool_use_id)

    async def _on_hook_subagent_started(self, ctx_data: dict[str, Any], tool_use_id: str) -> None:
        """Handle TOOL_EXECUTION_STARTED hook for a subagent tool."""
        input_preview = ctx_data.get("input_preview", "")
        event = self._subagents.on_task_started_from_hook(tool_use_id, input_preview)
        await self._collector.record_subagent_started(event.agent_name, tool_use_id)

    async def _on_hook_subagent_completed(self, ctx_data: dict[str, Any], tool_use_id: str) -> None:
        """Handle TOOL_EXECUTION_COMPLETED hook for a subagent tool."""
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

    @staticmethod
    def _parse_task_result(result_text: str) -> dict[str, Any] | None:
        """Extract the structured TASK_RESULT JSON block from a result string."""
        if "TASK_RESULT:" not in result_text:
            return None
        try:
            marker = "TASK_RESULT:"
            raw = result_text[result_text.rfind(marker) + len(marker) :].strip()
            brace_end = raw.find("}")
            if brace_end >= 0:
                raw = raw[: brace_end + 1]
            return json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            logger.debug("Could not parse TASK_RESULT block")
            return None

    def _capture_result_tokens(self, cli_event: dict[str, Any]) -> None:
        """Store authoritative cumulative token counts from a result event."""
        usage = cli_event.get("usage", {})
        self._result_input_tokens = usage.get("input_tokens", 0)
        self._result_output_tokens = usage.get("output_tokens", 0)
        self._result_cache_creation = usage.get("cache_creation_input_tokens", 0)
        self._result_cache_read = usage.get("cache_read_input_tokens", 0)
        self._result_cost_usd = cli_event.get("total_cost_usd")
        self._result_duration_ms = cli_event.get("duration_ms")
        self._result_num_turns = cli_event.get("num_turns")
        if self._result_input_tokens > 0 or self._result_output_tokens > 0:
            logger.info(
                "Result totals: cost=$%s, %d in, %d out (cache: %d read, %d create)",
                self._result_cost_usd,
                self._result_input_tokens,
                self._result_output_tokens,
                self._result_cache_read,
                self._result_cache_creation,
            )

    async def _handle_result_event(self, cli_event: dict[str, Any]) -> dict[str, Any] | None:
        """Handle a result event — extract task result and token usage."""
        result_text = cli_event.get("result", "")
        task_result = self._parse_task_result(result_text) if result_text else None
        if task_result:
            logger.info(
                "Agent task result: success=%s comments=%s",
                task_result.get("success"),
                str(task_result.get("comments", ""))[:100],
            )
        if cli_event.get("is_error") and result_text:
            self._error_reason = _extract_error_reason(result_text)
        self._capture_result_tokens(cli_event)
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

            cache_creation = usage.get("cache_creation_input_tokens", 0)
            cache_read = usage.get("cache_read_input_tokens", 0)

            if input_tokens > 0 or output_tokens > 0 or cache_creation > 0 or cache_read > 0:
                self._tokens.record(input_tokens, output_tokens, cache_creation, cache_read)
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
        if tool_name in _SUBAGENT_TOOL_NAMES and tool_use_id:
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
            await self._embedded_scanner.scan_and_record(str(tool_content), tool_name)

        # Record tool completion
        await self._collector.record_tool_completed(
            tool_name=tool_name,
            tool_use_id=tool_use_id,
            success=not is_error,
            output_preview=output_preview,
        )
        logger.debug("Tool completed: %s (%s) success=%s", tool_use_id, tool_name, not is_error)

        # ADR-037: Detect Task/Agent tool completion as subagent stop (raw CLI format)
        if tool_name in _SUBAGENT_TOOL_NAMES:
            await self._record_subagent_completion(tool_use_id, is_error)
        else:
            # Attribute non-subagent tool to the most recently started subagent
            self._subagents.attribute_tool(tool_name)

    async def _record_subagent_completion(self, tool_use_id: str, is_error: bool) -> None:
        """Record subagent completion from raw CLI tool_result."""
        event = self._subagents.on_task_completed(tool_use_id, success=not is_error)
        if event:
            await self._collector.record_subagent_stopped(
                agent_name=event.agent_name,
                tool_use_id=tool_use_id,
                duration_ms=event.duration_ms,
                success=event.success,
                tools_used=event.tools_used,
            )
