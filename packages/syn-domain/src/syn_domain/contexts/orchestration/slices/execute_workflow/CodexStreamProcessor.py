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
import re
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, TypedDict

from syn_domain.contexts.orchestration.slices.execute_workflow.CancelSignalPoller import (
    CancelSignalPoller,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.EventStreamProcessor import (
    ApiErrorType,
    InterruptibleWorkspace,
    StreamResult,
    api_error_label,
)
from syn_shared.agents import AgentProvider
from syn_shared.codex_stream import (
    CODEX_TOOL_NAME_COMMAND,
    CODEX_TOOL_NAME_FILE_CHANGE,
    CodexItemType,
    CodexStreamType,
)
from syn_shared.delegation import (
    DELEGATION_TARGET_BY_PRIMARY,
    DelegationTarget,
    looks_like_delegation_command,
)
from syn_shared.pricing import resolve_model_pricing

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from syn_adapters.control import ExecutionController
    from syn_domain.contexts.orchestration.slices.execute_workflow.TokenAccumulator import (
        TokenAccumulator,
    )

logger = logging.getLogger(__name__)

# This processor drives a CODEX primary, so its declared delegate is claude -p.
DELEGATION_TARGET: DelegationTarget = DELEGATION_TARGET_BY_PRIMARY[AgentProvider.CODEX]

# --- Terminal faults the codex CLI reports on stdout as NON-JSON log lines ----
#
# The codex CLI writes tracing lines to the same stdout as its JSON events. Most
# are inert noise (see module docstring) and are rightly discarded, but a login
# failure is announced ONLY there:
#
#   ERROR codex_login::auth::manager: Failed to refresh token: 401 Unauthorized
#   ... "code": "refresh_token_reused"
#
# Discarding it meant an expired codex login surfaced downstream as "codex
# stream ended without a terminal turn.completed event" - a true statement
# about a symptom that names the wrong subsystem and gives an operator nothing
# to act on (issue #891).
#
# THREE conditions, ALL required. Each rejects lines the other two accept.
#
#   1. error severity, ANCHORED to the tracing-line format,
#   2. auth CONTEXT (the codex_login target, or an auth:: module path),
#   3. an explicit auth-FAILURE marker.
#
# Why each is needed, with the line that motivates it:
#
# (1) anchored severity. A severity word can appear anywhere in a line,
#     including inside captured command output:
#
#       INFO codex_exec: command output: ERROR deleting file: unauthorized operation
#
#     A file-deletion failure is not an auth failure. Matching `ERROR`
#     anywhere would diagnose it as one. The tracing format puts the severity
#     first, so that is where it is required.
#
# (2) auth context. The golden fixture carries a routine
#     `ERROR codex_models_manager::manager: ...` diagnostic; without an auth
#     requirement, a severity+marker filter would promote unrelated subsystem
#     errors into authentication verdicts.
#
# (3) a failure marker. The subsystem NAME is not evidence of a fault -
#     healthy lines carry it too:
#
#       INFO codex_login::auth::manager: loaded cached credentials
#
#     An early draft ORed its alternatives, so the bare name matched. Because
#     AgentExecutionHandler forces exit code 1 whenever a codex stream carries
#     any error_reason, that draft would have failed SUCCESSFUL codex phases -
#     a worse defect than the missing reason it set out to fix.
#
# The marker list is deliberately broader than the single production line that
# prompted #891. Real auth failures the CLI spells differently -
# "Authentication failed: HTTP 401", "token expired" - were falling through to
# the generic "stream ended without a terminal turn" message, which is exactly
# the misdiagnosis this exists to remove.
_TRACING_ERROR_SEVERITY_RE = re.compile(r"^\s*(?:ERROR|FATAL)\b")
_AUTH_CONTEXT_RE = re.compile(r"codex_login|auth::", re.IGNORECASE)
_AUTH_FAILURE_MARKER_RE = re.compile(
    r"failed to refresh token"
    r"|refresh_token_reused"
    r"|invalid_grant"
    r"|unauthorized"
    r"|authentication failed"
    r"|token expired"
    r"|login required"
    r"|\b(?:401|403)\b",
    re.IGNORECASE,
)
_HTTP_AUTH_STATUS_RE = re.compile(r"\b(401|403)\b")
_MAX_FAULT_LINE_LEN = 160

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
        agent_model: str | None,
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
        self._leader_native_session_id: str | None = None
        # Held, not applied. An auth error the CLI RECOVERS from (retry, then a
        # normal turn.completed) must not fail an otherwise successful phase,
        # so the candidate is only promoted at end-of-stream and only when no
        # terminal turn arrived.
        self._auth_fault_candidate: str | None = None

        # #894: A codex phase delegates to `claude -p`.
        self._delegation_tool_use_ids: set[str] = set()
        # codex can emit item.completed more than once for one item; without
        # this the same delegation would be counted repeatedly.
        self._delegation_completed_ids: set[str] = set()
        self._delegation_attempts: int = 0
        self._delegation_successes: int = 0

    async def process_stream(
        self,
        stream: AsyncIterator[str],
        workspace: InterruptibleWorkspace,
    ) -> StreamResult:
        """Process the JSONL event stream from ``codex exec --json``."""
        started_at = time.monotonic()
        conversation_lines: list[str] = []
        line_count = 0
        interrupt_requested = False
        interrupt_reason: str | None = None

        async for line in stream:
            line_count += 1
            if line.strip():
                conversation_lines.append(line)

            poll = await self._cancel_poller.check(line_count)
            if poll.should_interrupt:
                await workspace.interrupt()
                interrupt_requested = True
                interrupt_reason = poll.reason
                break

            await self._process_line(line)

        if not self._totals.saw_terminal_turn:
            self._error_reason = (
                self._error_reason
                or self._auth_fault_candidate
                or (
                    "codex stream ended without a terminal turn.completed event "
                    "(no authoritative usage)"
                )
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
            interrupt_requested=interrupt_requested,
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
            delegation_attempts=self._delegation_attempts,
            delegation_successes=self._delegation_successes,
            leader_native_session_id=self._leader_native_session_id,
        )

    def _estimate_cost(self) -> float | None:
        """Estimate total cost via the STRICT resolver (never Sonnet default).

        ``self._agent_model`` is ``None`` when the phase omitted `model:`
        (codex does not report its own model on the wire, so there is no
        authoritative id to resolve). Returning ``None`` here - rather than
        guessing a model to price against - leaves cost unpriced instead of
        confidently wrong (issue #788 follow-up).
        """
        if self._agent_model is None:
            return None
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
        if not stripped:
            return None
        if not stripped.startswith("{"):
            self._note_non_json_fault(stripped)
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

    def _note_non_json_fault(self, line: str) -> None:
        """Remember a recognisable auth fault seen on an inert CLI log line.

        Deliberately does NOT decide anything. It records a CANDIDATE reason;
        `process_stream` promotes it only if the stream never reached a
        terminal `turn.completed`. This widens what the parser SEES, not what
        it treats as fatal - a run that hits a transient auth error and then
        completes normally still succeeds.
        """
        if self._auth_fault_candidate is not None:
            return
        if not _TRACING_ERROR_SEVERITY_RE.search(line):
            return
        if not _AUTH_CONTEXT_RE.search(line):
            return
        if not _AUTH_FAILURE_MARKER_RE.search(line):
            return
        status = _HTTP_AUTH_STATUS_RE.search(line)
        label = api_error_label(
            ApiErrorType.AUTHENTICATION,
            status.group(1) if status else "",
        )
        self._auth_fault_candidate = f"{label}: codex CLI login - {line[:_MAX_FAULT_LINE_LEN]}"
        logger.warning("Codex auth fault seen on stdout: %s", line[:_MAX_FAULT_LINE_LEN])

    def _note_delegation_attempt(self, tool_use_id: str, command: str) -> None:
        """Record a codex command_execution that invokes `claude -p` (#894)."""
        if tool_use_id in self._delegation_tool_use_ids:
            return
        if not looks_like_delegation_command(command, DELEGATION_TARGET):
            return
        self._delegation_tool_use_ids.add(tool_use_id)
        self._delegation_attempts += 1
        logger.info("Delegation invocation detected (item=%s)", tool_use_id)

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
        elif event_type == CodexStreamType.THREAD_STARTED:
            # Codex announces its OWN session id here, and it is the same id
            # the rollout file on disk is keyed by - verified same-run, not
            # inferred from both being uuidv7. That identity is what lets the
            # delegate import dedup the leader by lookup instead of guessing
            # it from agent names (#895).
            #
            # FIRST wins, for the same reason as the claude side: a rebind
            # late in a run would make the real leader look like a delegate
            # and bill it a second time.
            announced = event.get("thread_id")
            if (
                self._leader_native_session_id is None
                and isinstance(announced, str)
                and announced.strip()
            ):
                self._leader_native_session_id = announced

        # "turn.started": no observability call needed.

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
        self._note_delegation_attempt(tool_use_id, command)
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
        # item.completed repeats the command, so a delegation is still counted
        # if the matching item.started never arrived (truncated stream).
        self._note_delegation_attempt(tool_use_id, str(item.get("command", "")))
        if (
            success
            and tool_use_id in self._delegation_tool_use_ids
            and tool_use_id not in self._delegation_completed_ids
        ):
            self._delegation_completed_ids.add(tool_use_id)
            self._delegation_successes += 1
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
