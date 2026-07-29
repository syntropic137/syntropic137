"""Codex stream processor for workflow execution.

Parses ``codex exec --json`` JSONL stdout into the SAME Lane-2
``ObservabilityCollector`` calls the claude ``EventStreamProcessor`` uses, so
a codex phase produces a real dashboard timeline (tool ops + tokens/cost).

This is a SIBLING to ``EventStreamProcessor``, not a refactor of it. The
claude parser is battle-tested and its stream shape (Claude Code
``stream-json``) is unrelated to codex's ``--json`` event shape
(``thread.started`` / ``turn.started`` / ``item.started`` / ``item.completed``
/ ``turn.completed``). Splitting a shared Strategy base is tracked as a
follow-up (see docs/superpowers/plans/2026-07-22-codex-bridge-integration.md,
Task 3) so the claude path stays byte-for-byte unchanged during this bridge.

Golden fixture note (2026-07-23): a real captured
``codex exec --json --full-auto`` recording
(``packages/syn-domain/tests/fixtures/codex/codex_exec_recording.jsonl``)
shows the codex CLI mixes NON-JSON lines into its stdout stream alongside the
JSONL events:

- a deprecation warning line (``warning: --full-auto is deprecated...``),
- a ``Reading additional input from stdin...`` banner line,
- a mid-stream ``ERROR codex_models_manager::manager: ...`` diagnostic line
  (looks like a tracing/log line, not JSON, not even ``{``-prefixed).

None of these are malformed JSON *events* - they are plain CLI noise that
happens to land on stdout. Treating every non-JSON line as fatal would fail
this golden recording, which does terminate normally with a single
``turn.completed``. So the parser only treats a line as a parse failure (and
sets ``StreamResult.error_reason``) when the line looks like it was meant to
be a JSON event (starts with ``{``) but fails to parse. Anything else is
inert stream noise: recorded into ``conversation_lines`` (provider-native,
NOT claude-shaped - downstream ``ConversationRecorder`` readers must tolerate
raw codex JSONL, including these interleaved non-JSON lines) and otherwise
ignored.

Also verified from the real fixture (contra the plan's documented schema,
which assumed ``item.item.id``): ``item`` fields live directly under the
``item`` key (``event["item"]["id"]``), not double-nested.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, TypedDict

from syn_domain.contexts.orchestration.slices.execute_workflow.CancelSignalPoller import (
    CancelSignalPoller,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.EventStreamProcessor import (
    InterruptibleWorkspace,
    StreamResult,
)
from syn_shared.codex_stream import (
    CODEX_TOOL_NAME_COMMAND,
    CODEX_TOOL_NAME_FILE_CHANGE,
    CodexItemType,
    CodexStreamType,
)
from syn_shared.pricing import resolve_model_pricing

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from syn_adapters.control import ExecutionController
    from syn_domain.contexts.orchestration.slices.execute_workflow.TokenAccumulator import (
        TokenAccumulator,
    )

logger = logging.getLogger(__name__)

_MAX_PREVIEW_LEN = 500


def _as_int(value: object) -> int:
    """Narrow a JSON-boundary ``object`` value (from ``dict.get``) to ``int``.

    Codex ``usage`` fields are always numeric on the wire; ``None``/missing
    values default to 0 rather than raising, matching the tolerant style of
    ``EventStreamProcessor``'s own ``usage.get(..., 0)`` accessors.
    """
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int | float):
        return int(value)
    return 0


class _CodexChange(TypedDict, total=False):
    """A single file change inside a codex ``file_change`` item."""

    path: str
    kind: str


class _CodexItem(TypedDict, total=False):
    """A codex stream ``item`` (command_execution / file_change / agent_message).

    ``total=False``: codex only populates the fields relevant to the item
    type, so every field is optional and read via ``.get(...)``.
    """

    id: str
    type: str
    command: str
    aggregated_output: str
    exit_code: int
    status: str
    changes: list[_CodexChange]


class _CodexUsage(TypedDict, total=False):
    """The ``usage`` block on a codex ``turn.completed`` event."""

    input_tokens: int
    cached_input_tokens: int
    output_tokens: int
    reasoning_output_tokens: int


class _CodexEvent(TypedDict, total=False):
    """A single codex ``--json`` stream event (typed JSON-boundary shape)."""

    type: str
    item: _CodexItem
    usage: _CodexUsage


class CodexObservabilityRecorder(Protocol):
    """Protocol for the Lane-2 recording surface the codex parser needs.

    Structurally matches ``ObservabilityCollector`` (see
    ``execute_workflow/ObservabilityCollector.py``); kept as a narrow Protocol
    here (rather than importing the concrete class) so tests can pass a
    duck-typed recorder without an import cycle, mirroring
    ``EventStreamProcessor.ObservabilityRecorder``.
    """

    async def record_tool_started(
        self,
        tool_name: str,
        tool_use_id: str,
        input_preview: str,
    ) -> None: ...

    async def record_tool_completed(
        self,
        tool_name: str,
        tool_use_id: str,
        success: bool,
        output_preview: str | None,
    ) -> None: ...

    async def record_token_usage(
        self,
        input_tokens: int,
        output_tokens: int,
        cache_creation: int = 0,
        cache_read: int = 0,
    ) -> None: ...

    async def record_session_summary(
        self,
        total_cost_usd: float | None,
        input_tokens: int,
        output_tokens: int,
        cache_creation: int,
        cache_read: int,
        num_turns: int | None,
        duration_ms: int | None,
        agent_id: str | None = None,
    ) -> None: ...


@dataclass
class _TurnUsage:
    """Normalized per-turn token usage derived from ``turn.completed.usage``.

    ``input_tokens`` on the wire INCLUDES ``cached_input_tokens`` (verified
    against the real fixture: ``input_tokens=97006``,
    ``cached_input_tokens=87808`` - fresh input is the difference, not the
    raw ``input_tokens`` value).
    """

    fresh_input: int
    cache_read: int
    billable_output: int

    @classmethod
    def from_usage(cls, usage: _CodexUsage) -> _TurnUsage:
        input_tokens = _as_int(usage.get("input_tokens"))
        cached_input_tokens = _as_int(usage.get("cached_input_tokens"))
        output_tokens = _as_int(usage.get("output_tokens"))
        reasoning_output_tokens = _as_int(usage.get("reasoning_output_tokens"))
        return cls(
            fresh_input=max(0, input_tokens - cached_input_tokens),
            cache_read=cached_input_tokens,
            billable_output=output_tokens + reasoning_output_tokens,
        )


@dataclass
class _CodexTotals:
    """Running sums across all turns seen in a codex stream."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read: int = 0
    turns: int = 0
    saw_terminal_turn: bool = False

    def add_turn(self, usage: _TurnUsage) -> None:
        self.input_tokens += usage.fresh_input
        self.output_tokens += usage.billable_output
        self.cache_read += usage.cache_read
        self.turns += 1
        self.saw_terminal_turn = True


class CodexStreamProcessor:
    """Processes a ``codex exec --json`` JSONL event stream.

    Mirrors the thin outer loop of ``EventStreamProcessor.process_stream``
    (cancel-poll + line accumulation) but dispatches on the codex event
    schema and feeds the SAME ``ObservabilityCollector`` interface. Returns
    the SAME ``StreamResult`` dataclass so downstream code (handler, phase
    result builder) does not need a codex-specific result type.
    """

    def __init__(
        self,
        tokens: TokenAccumulator,
        collector: CodexObservabilityRecorder,
        controller: ExecutionController | None,
        execution_id: str,
        phase_id: str,
        session_id: str,
        agent_model: str,
    ) -> None:
        self._tokens = tokens
        self._collector = collector
        self._execution_id = execution_id
        self._phase_id = phase_id
        self._session_id = session_id
        self._agent_model = agent_model
        self._cancel_poller = CancelSignalPoller(
            controller=controller,
            execution_id=execution_id,
        )
        self._totals = _CodexTotals()
        self._error_reason: str | None = None

    async def process_stream(
        self,
        stream: AsyncIterator[str],
        workspace: InterruptibleWorkspace,
    ) -> StreamResult:
        """Process the JSONL event stream from ``codex exec --json``."""
        started_at = time.monotonic()
        conversation_lines: list[str] = []
        line_count = 0
        interrupt_reason: str | None = None

        async for line in stream:
            line_count += 1
            if line.strip():
                conversation_lines.append(line)

            poll = await self._cancel_poller.check(line_count)
            if poll.should_interrupt:
                await workspace.interrupt()
                interrupt_reason = poll.reason
                break

            await self._process_line(line)

        if not self._totals.saw_terminal_turn:
            self._error_reason = self._error_reason or (
                "codex stream ended without a terminal turn.completed event "
                "(no authoritative usage)"
            )

        total_cost_usd = self._estimate_cost()
        duration_ms = int((time.monotonic() - started_at) * 1000)

        await self._collector.record_session_summary(
            total_cost_usd=total_cost_usd,
            input_tokens=self._totals.input_tokens,
            output_tokens=self._totals.output_tokens,
            cache_creation=0,
            cache_read=self._totals.cache_read,
            num_turns=self._totals.turns or None,
            duration_ms=duration_ms,
            agent_id=None,
        )

        logger.info(
            "Codex runner streaming complete: %d lines, %d turns, cost=$%s (%d in, %d out)",
            line_count,
            self._totals.turns,
            total_cost_usd,
            self._totals.input_tokens,
            self._totals.output_tokens,
        )

        return StreamResult(
            line_count=line_count,
            interrupt_requested=interrupt_reason is not None,
            interrupt_reason=interrupt_reason,
            agent_task_result=None,
            conversation_lines=conversation_lines,
            total_cost_usd=total_cost_usd,
            result_input_tokens=self._totals.input_tokens,
            result_output_tokens=self._totals.output_tokens,
            result_cache_creation=0,
            result_cache_read=self._totals.cache_read,
            duration_ms=duration_ms,
            num_turns=self._totals.turns,
            error_reason=self._error_reason,
        )

    def _estimate_cost(self) -> float | None:
        """Estimate total cost via the STRICT resolver (never Sonnet default)."""
        pricing = resolve_model_pricing(self._agent_model)
        if pricing is None:
            return None
        return float(
            pricing.calculate_cost(
                self._totals.input_tokens,
                self._totals.output_tokens,
                cache_creation=0,
                cache_read=self._totals.cache_read,
            )
        )

    def _parse_event(self, line: str) -> _CodexEvent | None:
        """Parse one stdout line into a codex event, or ``None`` to skip it.

        Lines that don't even look like JSON (don't start with ``{``) are inert
        CLI noise (warnings, banners, interleaved log lines - see module
        docstring) and are silently skipped: neither recorded nor treated as
        failures. A ``{``-prefixed line that fails to parse is a real broken
        event - it sets ``error_reason`` (the handler forces a non-zero phase
        exit) and is skipped.
        """
        stripped = line.strip()
        if not stripped or not stripped.startswith("{"):
            return None

        try:
            event: _CodexEvent = json.loads(stripped)
        except json.JSONDecodeError:
            logger.debug("Malformed codex JSON line: %s", stripped[:100])
            self._error_reason = self._error_reason or (
                f"malformed codex JSON line: {stripped[:100]}"
            )
            return None

        if not isinstance(event, dict):
            return None
        return event

    async def _process_line(self, line: str) -> None:
        """Parse and dispatch a single codex JSONL line."""
        event = self._parse_event(line)
        if event is None:
            return

        event_type = event.get("type", "")
        if event_type == CodexStreamType.ITEM_STARTED:
            await self._handle_item_started(event)
        elif event_type == CodexStreamType.ITEM_COMPLETED:
            await self._handle_item_completed(event)
        elif event_type == CodexStreamType.TURN_COMPLETED:
            await self._handle_turn_completed(event)
        # "thread.started" / "turn.started": no observability call needed.

    async def _handle_item_started(self, event: _CodexEvent) -> None:
        """Handle ``item.started``: only ``command_execution`` starts a tool op.

        ``file_change`` items only carry useful data on ``item.completed``
        (the change list), so they are recorded as a synthetic
        started+completed pair there instead (see ``_handle_item_completed``).
        """
        item = event.get("item")
        if not isinstance(item, dict) or item.get("type") != CodexItemType.COMMAND_EXECUTION:
            return

        tool_use_id = str(item.get("id", "unknown"))
        command = str(item.get("command", ""))
        await self._collector.record_tool_started(
            tool_name=CODEX_TOOL_NAME_COMMAND,
            tool_use_id=tool_use_id,
            input_preview=command[:_MAX_PREVIEW_LEN],
        )

    async def _handle_item_completed(self, event: _CodexEvent) -> None:
        """Handle ``item.completed`` for command_execution and file_change items."""
        item = event.get("item")
        if not isinstance(item, dict):
            return

        item_type = item.get("type")
        if item_type == CodexItemType.COMMAND_EXECUTION:
            await self._handle_command_execution_completed(item)
        elif item_type == CodexItemType.FILE_CHANGE:
            await self._handle_file_change_completed(item)
        # "agent_message" items are conversational text, not a tool op.

    async def _handle_command_execution_completed(self, item: _CodexItem) -> None:
        tool_use_id = str(item.get("id", "unknown"))
        exit_code = item.get("exit_code")
        success = exit_code == 0
        output = str(item.get("aggregated_output") or "")
        if not success:
            # A failed inner command is a failed TOOL op, not automatically a
            # failed codex run (docs/superpowers/plans/2026-07-22-codex-bridge-integration.md
            # "Exit + failure semantics"). Logged for operator visibility;
            # deliberately does NOT set self._error_reason (that field is
            # reserved for the hard "stream is broken" signal the handler
            # uses to force a non-zero phase exit).
            logger.warning(
                "Codex command_execution %s exited non-zero: exit_code=%s",
                tool_use_id,
                exit_code,
            )
        await self._collector.record_tool_completed(
            tool_name=CODEX_TOOL_NAME_COMMAND,
            tool_use_id=tool_use_id,
            success=success,
            output_preview=output[:_MAX_PREVIEW_LEN] if output else None,
        )

    async def _handle_file_change_completed(self, item: _CodexItem) -> None:
        tool_use_id = str(item.get("id", "unknown"))
        changes = item.get("changes")
        paths = (
            [str(change.get("path", "")) for change in changes if isinstance(change, dict)]
            if isinstance(changes, list)
            else []
        )
        preview = ", ".join(paths)[:_MAX_PREVIEW_LEN]
        success = item.get("status") != "failed"

        await self._collector.record_tool_started(
            tool_name=CODEX_TOOL_NAME_FILE_CHANGE,
            tool_use_id=tool_use_id,
            input_preview=preview,
        )
        await self._collector.record_tool_completed(
            tool_name=CODEX_TOOL_NAME_FILE_CHANGE,
            tool_use_id=tool_use_id,
            success=success,
            output_preview=preview or None,
        )

    async def _handle_turn_completed(self, event: _CodexEvent) -> None:
        usage = event.get("usage")
        if not isinstance(usage, dict):
            return

        turn_usage = _TurnUsage.from_usage(usage)
        self._totals.add_turn(turn_usage)

        self._tokens.record(
            turn_usage.fresh_input,
            turn_usage.billable_output,
            0,
            turn_usage.cache_read,
        )
        await self._collector.record_token_usage(
            turn_usage.fresh_input,
            turn_usage.billable_output,
            cache_creation=0,
            cache_read=turn_usage.cache_read,
        )
