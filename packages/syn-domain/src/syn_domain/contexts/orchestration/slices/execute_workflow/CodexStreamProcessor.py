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
``turn.completed``. So no single line fails a run: unrecognised lines are
inert stream noise, recorded into ``conversation_lines`` (provider-native,
NOT claude-shaped - downstream ``ConversationRecorder`` readers must tolerate
raw codex JSONL, including these interleaved non-JSON lines) and otherwise
ignored.

That holds for ``{``-leading lines too (issue #1146). stdout carries the
agent's OWN subprocess output as well as the codex event stream (ADR-043,
deliberately), so a leading ``{`` is not evidence a line was meant to be an
event - JSX/TSX interpolation, JSON-with-comments, ``{{ handlebars }}`` and
shell brace expansion all start that way, and a codex phase asked to read a
dashboard file will echo them. Treating one as a protocol fault failed a
``verify`` phase over a line of TSX from the repository under review. Such a
line is therefore held as a CANDIDATE reason and promoted only if the stream
never reaches ``turn.completed``; a run that echoes one and then completes
normally succeeds.

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
from typing import TYPE_CHECKING, Final, Protocol, TypedDict

from syn_domain.contexts.agent_sessions import model_from_rollout
from syn_domain.contexts.orchestration.slices.execute_workflow.announced_model import (
    announced_model_from,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.CancelSignalPoller import (
    CancelSignalPoller,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.EventStreamProcessor import (
    ApiErrorType,
    InterruptibleWorkspace,
    ReportedUsage,
    StreamResult,
    api_error_label,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.held_token_rows import HeldTokenRows
from syn_domain.contexts.orchestration.slices.execute_workflow.phase_verdict import (
    VerdictReader,
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
from syn_shared.observed_model import RecordedModel
from syn_shared.pricing import resolve_model_pricing

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from syn_adapters.control import ExecutionController
    from syn_domain.contexts.orchestration.ports import CodexRolloutPort
    from syn_domain.contexts.orchestration.slices.execute_workflow.TokenAccumulator import (
        TokenAccumulator,
    )

logger = logging.getLogger(__name__)

#: The reason recorded when a codex stream carries no fault of its own and
#: simply stops before `turn.completed`. It is a TELEMETRY gap - the run has no
#: authoritative usage - and it is deliberately distinguishable from every other
#: value `error_reason` can take, all of which name a real fault (a login
#: failure, a malformed line). AgentExecutionHandler relies on that distinction:
#: it will let a phase that reached this state complete IF the phase actually
#: produced a deliverable, and only this state (issue #1111).
MISSING_TERMINAL_TURN_REASON: Final[str] = (
    "codex stream ended without a terminal turn.completed event (no authoritative usage)"
)

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


def codex_fault_reason(message: str) -> str:
    """The reason text codex's own words about a failed turn are reported under.

    A function rather than an f-string at the one call site because it is not
    only written here: `busy_upstream` has to RECOGNISE a specific sentence
    codex says about its own capacity, and it can only do that against the
    exact spelling this produces. Two copies of that spelling would drift the
    first time either the prefix or the truncation changed, and the failure
    would be silent - a phase that stopped being retried, with nothing to read
    but the reason it was never retried for.
    """
    return f"codex reported: {message[:_MAX_FAULT_LINE_LEN]}"


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
    #: Prose, on ``agent_message`` items only. It is where codex states its
    #: conclusion, and the only copy of that conclusion when the file the
    #: phase was supposed to write turns out to be empty (#1195).
    text: str


def _changed_paths_preview(item: _CodexItem) -> str:
    """The paths a ``file_change`` item touched, as one preview string.

    Both ends of a file change carry the same change list, and both record it
    - the start as its ``input_preview``, the completion as its
    ``output_preview`` - so the reading of it lives in one place.
    """
    changes = item.get("changes")
    paths = (
        [str(change.get("path", "")) for change in changes if isinstance(change, dict)]
        if isinstance(changes, list)
        else []
    )
    return ", ".join(paths)[:_MAX_PREVIEW_LEN]


class _CodexUsage(TypedDict, total=False):
    """The ``usage`` block on a codex ``turn.completed`` event."""

    input_tokens: int
    cached_input_tokens: int
    output_tokens: int
    reasoning_output_tokens: int


class _CodexError(TypedDict, total=False):
    """The ``error`` block on a codex ``turn.failed`` event."""

    message: str


class _CodexEvent(TypedDict, total=False):
    """A single codex ``--json`` stream event (typed JSON-boundary shape)."""

    type: str
    item: _CodexItem
    usage: _CodexUsage
    error: _CodexError
    message: str
    #: Declared but NOT observed: no captured codex stream carries it (see
    #: `_process_line`). Declared anyway because the parser reads it, and a key
    #: the parser reads should be in the shape a reader consults.
    model: str


class CodexObservabilityRecorder(Protocol):
    """Protocol for the Lane-2 recording surface the codex parser needs.

    Structurally matches ``ObservabilityCollector`` (see
    ``execute_workflow/ObservabilityCollector.py``); kept as a narrow Protocol
    here (rather than importing the concrete class) so tests can pass a
    duck-typed recorder without an import cycle, mirroring
    ``EventStreamProcessor.ObservabilityRecorder``.
    """

    def note_agent_activity(self) -> None:
        """See ``ObservabilityCollector.note_agent_activity`` (#1303)."""
        ...

    def note_observed_model(self, model: str | None) -> None:
        """See ``ObservabilityCollector.note_observed_model`` (ADR-067)."""
        ...

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
        model: str | None = None,
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
        totals_are_authoritative: bool = True,
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
        rollout: CodexRolloutPort | None,
    ) -> None:
        self._tokens = tokens
        #: Where the model comes from when the stream does not name one, which
        #: so far is every codex run there has ever been (#1284). Stated by
        #: every caller and given no default on purpose: `None` here means
        #: NOBODY LOOKED, and that has to be a decision someone made rather
        #: than a keyword they omitted - the omission is the exact shape of the
        #: bug this parameter exists to close.
        self._rollout = rollout
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
        self._last_agent_message: str | None = None
        # Same two questions, same two fields as the claude processor: last
        # words for the artifact fallback, and a verdict read per message so a
        # report cannot be overwritten before it is parsed (#1256).
        self._verdict_reader = VerdictReader()
        self._leader_native_session_id: str | None = None
        #: The model codex NAMED, on its own stream or failing that in the
        #: rollout it wrote (#1284). FIRST wins, the rule and reason of
        #: `_leader_native_session_id` directly above.
        #:
        #: `_agent_model` (the REQUESTED model) is deliberately not a fallback
        #: here. It is frequently a Claude alias that was never forwarded to
        #: `codex exec` at all (see `_is_codex_model` in
        #: `apps/syn-api/_codex_command.py`), so copying it in would record
        #: "claude ran the codex phase" - a false statement that reads as
        #: evidence. None is the honest answer and the one `AgentIdentity`
        #: already defines as "not reported".
        self._announced_model: str | None = None
        # Held, not applied. An auth error the CLI RECOVERS from (retry, then a
        # normal turn.completed) must not fail an otherwise successful phase,
        # so the candidate is only promoted at end-of-stream and only when no
        # terminal turn arrived.
        self._auth_fault_candidate: str | None = None
        #: A fault codex reported on `error` / `turn.failed`, held until
        #: end-of-stream so a recovered turn is not failed by it (#1117).
        self._turn_fault_candidate: str | None = None
        #: A `{`-leading line that would not parse, held until end-of-stream
        #: for the same reason (#1146). LAST one wins, unlike the two above:
        #: these lines carry no specificity gradient to preserve, and when the
        #: candidate is informative at all it is because the stream was cut
        #: off - which is the last such line, not the first.
        self._parse_fault_candidate: str | None = None

        # #894: A codex phase delegates to `claude -p`.
        self._delegation_tool_use_ids: set[str] = set()
        # codex can emit item.completed more than once for one item; without
        # this the same delegation would be counted repeatedly.
        self._delegation_completed_ids: set[str] = set()
        self._delegation_attempts: int = 0
        self._delegation_successes: int = 0

        #: Per-turn usage rows HELD until the model is known (ADR-067 D9); the
        #: live accumulator (`self._tokens`) is still fed per turn.
        self._held_rows = HeldTokenRows(collector, phase_id)

    async def process_stream(
        self,
        stream: AsyncIterator[str],
        workspace: InterruptibleWorkspace,
    ) -> StreamResult:
        """Process the JSONL event stream from ``codex exec --json``.

        Every held usage row is written before this returns or raises: after
        the rollout read on the normal path (so rows carry the model codex
        ran), and in the `finally` otherwise, with whatever model is known.
        """
        try:
            return await self._process_stream(stream, workspace)
        finally:
            await self._held_rows.flush(self._announced_model, raise_errors=False)

    async def _process_stream(
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
            # THE single place `_error_reason` is decided. Nothing mid-stream
            # writes it: every fault the parser can see is held as a candidate
            # and settled here, so a stream that recovers and reaches
            # `turn.completed` cannot be failed by something it recovered from.
            #
            # Order is deliberate, most specific first: a fault codex itself
            # reported beats an inferred auth fault, which beats an unparseable
            # `{`-leading line, which beats the generic "it just stopped".
            #
            # The parse fault ranks LAST of the three because it is the weakest
            # evidence - the line may be output the agent echoed, wholly
            # unrelated to why the stream stopped (#1146). It still outranks
            # `MISSING_TERMINAL_TURN_REASON` because when a stream IS cut off
            # mid-event, quoting the truncated line names the cause and the
            # generic reason does not.
            self._error_reason = (
                self._turn_fault_candidate
                or self._auth_fault_candidate
                or self._parse_fault_candidate
                or MISSING_TERMINAL_TURN_REASON
            )

        await self._name_the_model_from_disk()
        await self._held_rows.flush(self._announced_model, raise_errors=True)

        total_cost_usd = self._estimate_cost()
        duration_ms = int((time.monotonic() - started_at) * 1000)

        # A codex stream that never reached `turn.completed` was cut off, so
        # these totals are what was observed before it stopped, not codex's
        # own final accounting. Same distinction the claude path draws (#1164);
        # the numbers are the running accumulator's either way, so the flag is
        # the only thing that tells a truncated run from a complete one.
        await self._collector.record_session_summary(
            total_cost_usd=total_cost_usd,
            input_tokens=self._totals.input_tokens,
            output_tokens=self._totals.output_tokens,
            cache_creation=0,
            cache_read=self._totals.cache_read,
            num_turns=self._totals.turns or None,
            duration_ms=duration_ms,
            totals_are_authoritative=self._totals.saw_terminal_turn,
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
            # The same reader as the claude path, and now the same TIMING
            # too: TASK_RESULT is this platform's contract with its agents,
            # not a harness format, so a codex phase that reports failure is
            # failed for the same reason and by the same code - including when
            # it goes on talking afterwards (#1256).
            verdict=self._verdict_reader.verdict,
            conversation_lines=conversation_lines,
            total_cost_usd=total_cost_usd,
            # Present only when codex reached `turn.completed`. A stream that
            # was cut off has an accumulator, not a report, and saying so here
            # is what stops the handler treating a truncated run's partial sum
            # as codex's own final accounting (#1164). The numbers are the same
            # either way - `_handle_turn_completed` feeds `_totals` and the
            # shared accumulator the same per-turn values - so this settles
            # what they MEAN, which is the part downstream cannot re-derive.
            reported_usage=ReportedUsage(
                input_tokens=self._totals.input_tokens,
                output_tokens=self._totals.output_tokens,
                cache_creation=0,
                cache_read=self._totals.cache_read,
            )
            if self._totals.saw_terminal_turn
            else None,
            duration_ms=duration_ms,
            num_turns=self._totals.turns,
            error_reason=self._error_reason,
            delegation_attempts=self._delegation_attempts,
            delegation_successes=self._delegation_successes,
            leader_native_session_id=self._leader_native_session_id,
            last_agent_message=self._last_agent_message,
            # Stated, not defaulted. The value is None for every codex stream
            # observed so far, but arriving by omission is what left a codex
            # artifact unable to say whether it had no model or had never been
            # asked - and the codex phase is the OTHER half of every
            # cross-model claim this platform makes (#1284).
            announced_model=self._announced_model,
        )

    async def _name_the_model_from_disk(self) -> None:
        """Ask the rollout what ran, because the stream never says.

        THIS IS NOT A FALLBACK IN PRACTICE, it is the path. No codex version
        captured here puts a model anywhere on stdout, across every fixture and
        the golden recording, so the check above this one has never once
        fired - which left every codex artifact reading
        `provider="codex", model=null` and proving harness diversity where the
        claim being made was model diversity (#1284). Codex does say what it
        ran; it says it on disk, in the same `turn_context.payload.model` that
        prices a codex delegate, read here by that same function.

        Runs at end-of-stream, once, and only when the stream named nothing:
        the rollout is complete by then and the workspace is still alive, and a
        stream that DID name a model needs no second opinion.

        Nothing here can fail the phase. A model that cannot be recovered is a
        gap in what we can say about the run, not a defect in the run, and the
        three ways of getting there are kept apart in the log because only one
        of them is an operational fault:

        - no rollout source wired          -> nobody looked;
        - source read nothing (`None`)     -> looked, could not read;
        - rollout named no single model    -> read, it does not say.

        All three leave `_announced_model` as None, which is the honest answer
        and the one `AgentIdentity` already defines as "not reported".
        """
        if self._announced_model is not None:
            return
        if self._rollout is None:
            logger.debug(
                "No codex rollout source wired (phase=%s) - the model this phase "
                "ran goes unrecorded",
                self._phase_id,
            )
            return
        if self._leader_native_session_id is None:
            # The rollout is filed under the id codex announced, and picking
            # one by any other means is a guess. A phase whose stream never got
            # as far as `thread.started` has no key, so there is nothing to
            # ask with.
            logger.warning(
                "Codex announced no session id (phase=%s) - cannot match its rollout, "
                "so the model it ran goes unrecorded",
                self._phase_id,
            )
            return

        document = await self._rollout.codex_rollout(self._leader_native_session_id)
        if document is None:
            logger.warning(
                "Could not read the codex rollout for session %s (phase=%s) - "
                "the model it ran goes unrecorded",
                self._leader_native_session_id,
                self._phase_id,
            )
            return

        self._announced_model = model_from_rollout(document)
        if self._announced_model is None:
            logger.info(
                "Codex rollout for session %s (phase=%s) names no single model",
                self._leader_native_session_id,
                self._phase_id,
            )

    def _estimate_cost(self) -> float | None:
        """Estimate total cost via the STRICT resolver (never Sonnet default).

        Priced as the model codex REPORTED (read from its rollout) when there
        is one, else as the requested model - ``RecordedModel.pricing_model``,
        the one rule every cost reader applies to the rows this writes, so the
        live estimate and a later re-read agree (ADR-067). With neither, the
        cost is left unpriced rather than guessed (issue #788 follow-up).
        """
        pricing_model = RecordedModel(
            observed=self._announced_model, requested=self._agent_model
        ).pricing_model
        if pricing_model is None:
            return None
        pricing = resolve_model_pricing(pricing_model)
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

        Every line here is skipped or dispatched; NONE of them fails the run on
        its own. Lines that don't look like JSON at all are inert CLI noise
        (warnings, banners, interleaved log lines - see module docstring). A
        ``{``-leading line that won't parse is held as a CANDIDATE reason,
        promoted by ``process_stream`` only if no ``turn.completed`` ever
        arrived - see the ``_parse_fault_candidate`` comment in ``__init__``
        for why it cannot be a verdict.
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
            logger.debug("Unparseable `{`-leading codex line: %s", stripped[:100])
            self._parse_fault_candidate = f"malformed codex JSON line: {stripped[:100]}"
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

        # Checked on EVERY event rather than one chosen type. No codex version
        # captured here emits a model anywhere on stdout - not the golden
        # recording, not any fixture - so there is no observed event to key
        # this to, and guessing one would be a schema we invented. Codex does
        # name its model on disk (`turn_context.payload.model` in the rollout,
        # which is where `transcript_usage` reads it), so the wire is where it
        # is missing, not the harness. Reading a top-level `model` off whatever
        # line carries it costs one lookup and needs no such guess: if codex
        # starts naming it, the identity is carried instead of dropped, and
        # until then this is None and every reader is told so.
        if self._announced_model is None:
            self._announced_model = announced_model_from(event.get("model"))

        event_type = event.get("type", "")
        if event_type == CodexStreamType.ITEM_STARTED:
            await self._handle_item_started(event)
        elif event_type == CodexStreamType.ITEM_COMPLETED:
            await self._handle_item_completed(event)
        elif event_type == CodexStreamType.TURN_COMPLETED:
            await self._handle_turn_completed(event)
        elif event_type in (CodexStreamType.TURN_FAILED, CodexStreamType.ERROR):
            self._note_stream_fault(event)
        elif event_type == CodexStreamType.THREAD_STARTED:
            self._note_leader_session_id(event)

        # "turn.started": no observability call needed.

    def _note_leader_session_id(self, event: _CodexEvent) -> None:
        """Record the session id codex announced for itself on ``thread.started``.

        It is the same id the rollout file on disk is keyed by - verified
        same-run, not inferred from both being uuidv7. That identity is what
        lets the delegate import dedup the leader by lookup instead of guessing
        it from agent names (#895), and it is the key
        `_name_the_model_from_disk` asks the rollout with (#1284).

        FIRST wins, for the same reason as the claude side: a rebind late in a
        run would make the real leader look like a delegate and bill it a
        second time. A blank or non-string announcement is not an id and is
        left unset, so the import refuses rather than deriving one shared
        platform id for every delegate.
        """
        announced = event.get("thread_id")
        if (
            self._leader_native_session_id is None
            and isinstance(announced, str)
            and announced.strip()
        ):
            self._leader_native_session_id = announced

    def _note_stream_fault(self, event: _CodexEvent) -> None:
        """Record the reason codex itself gave for ending the turn.

        WHY (issue #1116). When a turn fails, codex says why, in the stream:

            {"type":"error","message":"This content was flagged for possible
             cybersecurity risk..."}
            {"type":"turn.failed","error":{"message": <the same text>}}

        Neither event was dispatched, so the stream simply ended with no
        `turn.completed` and the run was reported as
        "codex stream ended without a terminal turn.completed event". True, and
        useless: it names the symptom, hides an operator-actionable cause, and
        makes an ordinary prompt rejection look like the same unexplained
        failure as a stream that stopped for reasons nobody has established.

        This is #891 again for a different event type, so it takes the same
        shape: keep the FIRST fault, because a later generic one must not
        overwrite the specific one that ended the run.

        AND IT IS A CANDIDATE, NOT A VERDICT. Setting `_error_reason` here
        directly would be worse than the bug it fixes. `AgentExecutionHandler`
        forces a non-zero phase exit whenever a codex stream carries ANY
        `error_reason`, and it does not consult `saw_terminal_turn`. So an
        `error` event the CLI then recovers from - `error` ... `turn.completed`
        - would fail a phase that finished cleanly, and would report the
        mid-turn hiccup as its cause. That does not mask a failure; it invents
        one. This module's own comment already names that class as the worse
        defect (an early #891 draft "would have failed SUCCESSFUL codex
        phases"), and the sibling `_note_non_json_fault` holds its result as a
        candidate for exactly this reason.

        So the message is held and promoted at end-of-stream only when no
        `turn.completed` arrived. A turn that genuinely failed emits no terminal
        turn, so the reason still surfaces; a turn that recovered keeps its
        success. Found by the cross-model review of #1117.
        """
        message = event.get("message")
        if not message:
            error = event.get("error")
            message = error.get("message") if error else None
        if not message:
            return
        reason = codex_fault_reason(message)
        logger.error("Codex turn failed: %s", message)
        # A CANDIDATE, not a verdict - promoted at end-of-stream only if no
        # terminal turn arrived. See the class comment above for why.
        self._turn_fault_candidate = self._turn_fault_candidate or reason

    async def _handle_item_started(self, event: _CodexEvent) -> None:
        """Handle ``item.started``: record the start codex announced, if any.

        A call is timed from the gap between the row that opens it and the row
        that closes it (`session_tools_dispatch.resolve_durations`), so what
        is recorded here decides whether that number means anything. Only what
        codex actually announces is recorded, and only when it announces it.

        ``command_execution`` is always opened before the command runs.
        ``file_change`` depends on the CLI version: some emit ``item.started``
        with the change list already on it and then ``item.completed``
        (`codex_exec_recording.jsonl`), others emit only ``item.completed``
        (`codex_brace_echo_clean.jsonl`). Where the start arrives the pair
        brackets the change and times it; where it does not, the completion
        stands alone and reports no duration, which is the answer every reader
        already gets for a completion with no start.
        """
        item = event.get("item")
        if not isinstance(item, dict):
            return

        # Before the type is read, and regardless of what it turns out to be.
        # Codex opens an item when it BEGINS the work, so any start at all -
        # an `agent_message` that never completes, a side-effecting type this
        # branch has never heard of - is the model having got somewhere. Only
        # the two below are worth an observation; all of them are worth the
        # fact, and that fact is what decides whether the whole prompt may be
        # run a second time over whatever the item did (#1303).
        self._collector.note_agent_activity()

        item_type = item.get("type")
        tool_use_id = str(item.get("id", "unknown"))

        if item_type == CodexItemType.COMMAND_EXECUTION:
            command = str(item.get("command", ""))
            self._note_delegation_attempt(tool_use_id, command)
            await self._collector.record_tool_started(
                tool_name=CODEX_TOOL_NAME_COMMAND,
                tool_use_id=tool_use_id,
                input_preview=command[:_MAX_PREVIEW_LEN],
            )
        elif item_type == CodexItemType.FILE_CHANGE:
            await self._collector.record_tool_started(
                tool_name=CODEX_TOOL_NAME_FILE_CHANGE,
                tool_use_id=tool_use_id,
                input_preview=_changed_paths_preview(item),
            )

    async def _handle_item_completed(self, event: _CodexEvent) -> None:
        """Handle ``item.completed`` for command_execution and file_change items."""
        item = event.get("item")
        if not isinstance(item, dict):
            return

        # And on completion too, not only on the start - some codex versions
        # announce a `file_change` only once it has happened (#1064), so the
        # completion can be the first and last the stream says about a
        # workspace mutation. Same rule as the start: any type counts.
        self._collector.note_agent_activity()

        item_type = item.get("type")
        if item_type == CodexItemType.COMMAND_EXECUTION:
            await self._handle_command_execution_completed(item)
        elif item_type == CodexItemType.FILE_CHANGE:
            await self._handle_file_change_completed(item)
        elif item_type == CodexItemType.AGENT_MESSAGE:
            # "agent_message" items are conversational text, not a tool op - so
            # they record no observability. They are kept anyway because they
            # are the only place codex states its conclusion in prose, and the
            # artifact path falls back to it when the file the phase wrote
            # turns out to be empty (#1195).
            said = str(item.get("text", ""))
            if said.strip():
                self._last_agent_message = said
                # Read in the turn that said it - see the claude processor's
                # `_handle_assistant_event`. This is the identical shape, so
                # it takes the identical fix rather than being left behind.
                self._verdict_reader.read(said)

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
        """Record the completion of a ``file_change``, and nothing else (#1064).

        This used to write a start here too, immediately before the
        completion, for the versions of codex that announce no
        ``item.started`` for a file change. That start was not an observation
        of anything: it said "this call began" from an event that says the
        call has ended, and the duration rule then measured the gap between
        this method's own two writes and reported it as how long the edit
        took - a few milliseconds or zero, depending on how fast the store
        answered. A number with the shape of a measurement and none of the
        content.

        A duration is only knowable from a pair of rows, so it is only
        reportable when the harness produced a pair. `_handle_item_started`
        records one end when codex announces it; this records the other. When
        codex announced no start, that leaves the duration `None` - what this
        producer actually knows.
        """
        preview = _changed_paths_preview(item)
        await self._collector.record_tool_completed(
            tool_name=CODEX_TOOL_NAME_FILE_CHANGE,
            tool_use_id=str(item.get("id", "unknown")),
            success=item.get("status") != "failed",
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
        # Held, not written: see `held_token_rows`.
        self._held_rows.hold(turn_usage)
