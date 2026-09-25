"""ObservabilityCollector — Lane 2 telemetry recording (ISS-196).

Encapsulates all observability recording calls. Never touches domain
aggregates — purely writes to the observability backend.

Extracted from EventStreamProcessor to enforce two-lane separation.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from syn_domain.contexts.agent_sessions import ObservationType, SessionSummaryData
from syn_domain.contexts.orchestration.slices.execute_workflow.announced_model import (
    announced_model_from,
)
from syn_shared.events import SESSION_SUMMARY
from syn_shared.observed_model import OBSERVED_MODEL_KEY, REQUESTED_MODEL_KEY
from syn_shared.pricing import cost_json_number

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration.slices.execute_workflow.EventStreamProcessor import (
        ObservabilityRecorder,
    )

logger = logging.getLogger(__name__)


def _build_embedded_data(enriched: dict[str, Any]) -> dict[str, Any]:
    """Build observation data dict from an embedded event.

    For structured events (v2, context contains a "git" sub-object),
    preserves the structure so downstream projections can read typed
    fields directly.

    For legacy flat events, flattens context + metadata and renames
    "message" to "commit_message" to avoid RESERVED_OBSERVATION_KEYS
    collision.
    """
    context = enriched.get("context") or {}
    metadata = enriched.get("metadata") or {}

    if "git" in context:
        # Structured payload (v2) - preserve context.git sub-object.
        # "message" lives at data.git.message, not data.message,
        # so no collision with RESERVED_OBSERVATION_KEYS.
        data: dict[str, Any] = {**context}
        if metadata:
            data.update(metadata)
        return data

    # Legacy flat format - flatten + rename reserved keys
    data = {**context, **metadata}
    # "message" is reserved by AgentEvent.from_dict() for Claude CLI
    # conversation messages (dict with "content" list). Git hooks emit
    # "message" as a plain string (commit message), which would be
    # stripped by record_observation. Rename to "commit_message".
    if "message" in data and isinstance(data["message"], str):
        data["commit_message"] = data.pop("message")
    return data


class ObservabilityCollector:
    """Lane 2: Records telemetry to observability backend.

    Never touches domain aggregates. All methods are no-op
    when the writer is None (e.g., in tests or local dev).
    """

    def __init__(
        self,
        writer: ObservabilityRecorder | None,
        session_id: str,
        execution_id: str,
        phase_id: str,
        workspace_id: str | None,
        requested_model: str | None,
    ) -> None:
        self._writer = writer
        self._session_id = session_id
        self._execution_id = execution_id
        self._phase_id = phase_id
        self._workspace_id = workspace_id
        #: What the phase ASKED for, usually an alias (``opus``, ``gpt-sol``).
        #: Written to every usage row as ``requested_model`` and never as
        #: ``model``: an alias is a pointer, not a record of what ran (ADR-067).
        self._requested_model = requested_model
        #: What the harness REPORTED running, once it has said. None until then,
        #: and for a harness that never says.
        self._observed_model: str | None = None
        self._saw_agent_activity = False

    @property
    def requested_model(self) -> str | None:
        """The model the phase declared (often an alias), or None."""
        return self._requested_model

    @property
    def observed_model(self) -> str | None:
        """The model the harness reported running so far, or None (ADR-067)."""
        return self._observed_model

    def note_observed_model(self, model: str | None) -> None:
        """Record the model the harness REPORTED. First non-blank report wins.

        The same rule as ``announced_model_from`` and for the same reason: a
        delegate or subagent line arriving late must not rebind the leader's
        identity. ``None`` and blank are ignored, so a stream that says nothing
        leaves the session honestly unknown rather than blanking a real answer.
        """
        if self._observed_model is None:
            self._observed_model = announced_model_from(model)

    @property
    def has_writer(self) -> bool:
        """Whether this collector has an active writer."""
        return self._writer is not None

    @property
    def saw_agent_activity(self) -> bool:
        """Whether this phase's agent has been seen to do ANYTHING yet (#1303).

        The one place that knows, and deliberately the crudest question that
        can be asked: not "did a tool run", not "did the agent speak", but "did
        this stream carry any sign of the model having started". Both stream
        processors converge here - claude from assistant content and hook
        events, codex from `item.started`/`item.completed` - so this is the
        only answer that does not have to be asked per harness.

        FALSE IS THE STRONG CLAIM, and it is the one a retry rests on: the
        attempt was a launch that never started, so re-running the same prompt
        against the same workspace repeats nothing. Every contributor below
        therefore reports what it SAW rather than what it recognised. An
        assistant turn counts whatever its content blocks turn out to be, a
        codex item counts whatever type it turns out to be, and a hook event
        counts at all. Recognising the shape is how the narrower `saw_tool_use`
        this replaced came to answer False for thinking-only turns,
        hook-delivered tool calls and item types nobody had taught it - each of
        them an attempt that HAD got somewhere, reported as one that had not,
        and re-run over its own side effects.

        Set BEFORE the writer check on every method below, deliberately: this
        records what the AGENT did, which is true whether or not anyone is
        persisting it. Reading it off a stored observation instead would make a
        run with no observability writer - every unit test, and local dev -
        look like a run in which no agent ever touched anything.

        Cumulative across the attempts of one phase, because the collector is:
        once an attempt has got somewhere, that is still true of the phase on
        the attempt after it.
        """
        return self._saw_agent_activity

    def note_agent_activity(self) -> None:
        """Record that the agent was seen doing something, whatever it was.

        For the stream processors, which see events this collector is never
        told about: a turn whose content is only thinking, a content block of a
        type the parser has no branch for, a codex item type that did not exist
        when the parser was written. None of those is an observation to record -
        there is nothing meaningful to store - but every one of them is proof
        the model started, which is the whole of what `saw_agent_activity` is
        asked for.

        Idempotent, and one-way: nothing un-sees activity.
        """
        self._saw_agent_activity = True

    async def record_hook_event(self, enriched: dict[str, Any]) -> None:
        """Record an enriched hook event to observability.

        Counted as activity whatever the event says. A hook fires from inside
        the agent's own process, so its mere arrival is proof the harness got
        as far as running the agent - and the tool calls claude reports THIS
        way rather than as `tool_use` blocks are exactly the side effects a
        rerun would repeat (#1303).
        """
        self.note_agent_activity()
        if self._writer is None:
            return

        context = enriched.get("context") or {}
        metadata = enriched.get("metadata") or {}

        if "git" in context:
            # Structured payload (v2) - preserve context.git sub-object.
            # No field collision with RESERVED_OBSERVATION_KEYS because
            # git data is namespaced under a "git" key.
            hook_data: dict[str, Any] = {**context}
            if metadata:
                hook_data.update(metadata)
        else:
            # Legacy flat format - merge context + metadata
            hook_data = {**context, **metadata}

        await self._writer.record_observation(
            session_id=self._session_id,
            observation_type=enriched.get("event_type", "unknown"),
            data=hook_data,
            execution_id=self._execution_id,
            phase_id=self._phase_id,
            workspace_id=self._workspace_id,
        )

    async def record_token_usage(
        self,
        input_tokens: int,
        output_tokens: int,
        cache_creation: int = 0,
        cache_read: int = 0,
        model: str | None = None,
    ) -> None:
        """Record token usage observation.

        ``model`` is the model THIS TURN reported (claude repeats it on every
        assistant message, and a subagent's turn names its own). Without one
        the row takes the session's observed model so far, and without that it
        is None - never the requested alias, which travels separately as
        ``requested_model`` (ADR-067).
        """
        if self._writer is None:
            return
        row_model = announced_model_from(model) or self._observed_model

        await self._writer.record_observation(
            session_id=self._session_id,
            observation_type=ObservationType.TOKEN_USAGE,
            data={
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cache_creation_tokens": cache_creation,
                "cache_read_tokens": cache_read,
                OBSERVED_MODEL_KEY: row_model,
                # ALWAYS present, null included: the key's presence is how a
                # reader tells a row written under ADR-067 from a legacy one.
                REQUESTED_MODEL_KEY: self._requested_model,
            },
            execution_id=self._execution_id,
            phase_id=self._phase_id,
            workspace_id=self._workspace_id,
        )

    async def record_tool_started(
        self,
        tool_name: str,
        tool_use_id: str,
        input_preview: str,
    ) -> None:
        """Record tool execution started."""
        # Recorded when the tool is ANNOUNCED, not when it returns, so this can
        # only run ahead of the side effect and never behind it. Running ahead
        # costs a retry that would have been safe; running behind would repeat
        # work that was not.
        self.note_agent_activity()
        if self._writer is None:
            return

        await self._writer.record_observation(
            session_id=self._session_id,
            observation_type=ObservationType.TOOL_EXECUTION_STARTED,
            data={
                "tool_name": tool_name,
                "tool_use_id": tool_use_id,
                "input_preview": input_preview,
            },
            execution_id=self._execution_id,
            phase_id=self._phase_id,
            workspace_id=self._workspace_id,
        )

    async def record_tool_completed(
        self,
        tool_name: str,
        tool_use_id: str,
        success: bool,
        output_preview: str | None,
    ) -> None:
        """Record tool execution completed."""
        # A completion can arrive with no start before it: some codex versions
        # announce a `file_change` only once it has happened (#1064). That is a
        # workspace mutation, so it counts, and counting only starts would miss
        # exactly the tool op that already changed something.
        self.note_agent_activity()
        if self._writer is None:
            return

        await self._writer.record_observation(
            session_id=self._session_id,
            observation_type=ObservationType.TOOL_EXECUTION_COMPLETED,
            data={
                "tool_name": tool_name,
                "tool_use_id": tool_use_id,
                "success": success,
                "output_preview": output_preview,
            },
            execution_id=self._execution_id,
            phase_id=self._phase_id,
            workspace_id=self._workspace_id,
        )

    async def record_subagent_started(
        self,
        agent_name: str,
        tool_use_id: str,
    ) -> None:
        """Record subagent started.

        A subagent is a whole agent run, so a phase that started one has
        unambiguously got somewhere. Marked here as well as at the hook that
        usually precedes it because the native `Task` tool path reaches this
        method without one (#1303).
        """
        self.note_agent_activity()
        if self._writer is None:
            return

        await self._writer.record_observation(
            session_id=self._session_id,
            observation_type=ObservationType.SUBAGENT_STARTED,
            data={
                "agent_name": agent_name,
                "subagent_tool_use_id": tool_use_id,
            },
            execution_id=self._execution_id,
            phase_id=self._phase_id,
            workspace_id=self._workspace_id,
        )
        logger.info("Subagent started: %s (id=%s)", agent_name, tool_use_id)

    async def record_subagent_stopped(
        self,
        agent_name: str,
        tool_use_id: str,
        duration_ms: int | None,
        success: bool | None,
        tools_used: dict[str, int] | None,
    ) -> None:
        """Record subagent stopped.

        Counted for the same reason a start is, and separately from it: a
        truncated stream can deliver the completion whose start never arrived.
        """
        self.note_agent_activity()
        if self._writer is None:
            return

        await self._writer.record_observation(
            session_id=self._session_id,
            observation_type=ObservationType.SUBAGENT_STOPPED,
            data={
                "agent_name": agent_name,
                "subagent_tool_use_id": tool_use_id,
                "duration_ms": duration_ms,
                "success": success,
                "tools_used": tools_used,
            },
            execution_id=self._execution_id,
            phase_id=self._phase_id,
            workspace_id=self._workspace_id,
        )
        logger.info(
            "Subagent stopped: %s (id=%s, duration=%dms, tools=%s)",
            agent_name,
            tool_use_id,
            duration_ms or 0,
            tools_used,
        )

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
    ) -> None:
        """Record end-of-session summary with the run's final totals (ISS-217).

        Emits a session_summary observation so SessionCostProjection.on_session_summary()
        can replace accumulated estimates with the SDK-reported values.

        ``totals_are_authoritative`` says whether the harness reported these
        totals itself. It is False when the process was killed or timed out
        before it could, leaving the totals observed-so-far rather than final.
        Consumers need the distinction: authoritative totals REPLACE what was
        accumulated, estimated ones must never reduce it (#1164). It defaults
        to True so that summaries recorded before this flag existed keep their
        original replace semantics on replay.
        """
        if self._writer is None:
            return

        # Declared, so the type checker holds this against the same shape the
        # cost projections read it back with. Every key here is a key some
        # projection looks up by string, and a rename on one side used to be
        # invisible until a dashboard showed a zero.
        summary: SessionSummaryData = {
            # Canonicalised at ingest: the Claude CLI reports a JS double
            # (0.3056678 arrives as 0.30566780000000005), and this is the
            # first point the platform controls. Stored clean, every later
            # numeric read of the row is clean too.
            "total_cost_usd": None if total_cost_usd is None else cost_json_number(total_cost_usd),
            "total_input_tokens": input_tokens,
            "total_output_tokens": output_tokens,
            "cache_creation_tokens": cache_creation,
            "cache_read_tokens": cache_read,
            "num_turns": num_turns,
            "duration_ms": duration_ms,
            "model": self._observed_model,
            "requested_model": self._requested_model,
            "totals_are_authoritative": totals_are_authoritative,
        }

        await self._writer.record_observation(
            session_id=self._session_id,
            observation_type=SESSION_SUMMARY,
            # Copied because the recorder port still asks for a mutable,
            # value-untyped dict, which no declared payload shape satisfies.
            # Widening that port to a read-only mapping is the better fix and
            # is already flagged as its own change - see the note on
            # ``syn_adapters...capture_observation.ObservationRecorder``.
            data=dict(summary),
            execution_id=self._execution_id,
            phase_id=self._phase_id,
            workspace_id=self._workspace_id,
        )
        logger.info(
            "Session summary recorded (%s): cost=$%s, %d in, %d out, %d turns, %dms",
            "authoritative" if totals_are_authoritative else "estimated from observations",
            total_cost_usd,
            input_tokens,
            output_tokens,
            num_turns or 0,
            duration_ms or 0,
        )

    async def record_embedded_event(
        self,
        event_type: str,
        enriched: dict[str, Any],
    ) -> None:
        """Record an embedded event (e.g., git hook events from tool output).

        These are scanned out of a tool's OUTPUT, so the work they describe -
        a commit, a push - has already happened by the time one is seen.
        """
        self.note_agent_activity()
        if self._writer is None:
            return

        await self._writer.record_observation(
            session_id=self._session_id,
            observation_type=event_type,
            data=_build_embedded_data(enriched),
            execution_id=self._execution_id,
            phase_id=self._phase_id,
            workspace_id=self._workspace_id,
        )
