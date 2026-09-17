"""RecordOperation command handler - the write path for session operations."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from syn_domain.contexts.agent_sessions._shared.value_objects import OperationType
from syn_domain.contexts.agent_sessions.domain.events.agent_observation import ObservationType

if TYPE_CHECKING:
    from syn_domain.contexts.agent_sessions.domain.aggregate_session.AgentSessionAggregate import (
        AgentSessionAggregate,
    )
    from syn_domain.contexts.agent_sessions.domain.commands.RecordOperationCommand import (
        RecordOperationCommand,
    )
    from syn_domain.contexts.agent_sessions.ports.SessionObservationPort import (
        SessionObservationPort,
    )
    from syn_domain.repository import Repository

logger = logging.getLogger(__name__)

_MAX_PREVIEW_LEN = 500
"""Same ceiling the stream processors apply, so a timeline row looks the same
whichever writer produced it."""

#: How each kind of operation is named on the observation lane, which is the
#: only lane ``GET /sessions/{id}`` reads for ``operations`` (#1034).
#:
#: Total over ``OperationType`` on purpose - ``_observation_type`` asserts that,
#: so adding a member forces a decision here instead of silently falling
#: through to "not recorded", which is the failure this whole change exists to
#: remove. ``None`` is that decision stated out loud, never its default.
_OBSERVATION_TYPES: dict[OperationType, ObservationType | None] = {
    OperationType.TOOL_EXECUTION_STARTED: ObservationType.TOOL_EXECUTION_STARTED,
    OperationType.TOOL_EXECUTION_COMPLETED: ObservationType.TOOL_EXECUTION_COMPLETED,
    OperationType.TOOL_BLOCKED: ObservationType.TOOL_BLOCKED,
    OperationType.ERROR: ObservationType.ERROR,
    OperationType.MESSAGE_REQUEST: ObservationType.USER_PROMPT_SUBMITTED,
    # Deprecated aliases. They still arrive from older callers, and dropping
    # them here would reproduce the bug for exactly the writers least likely to
    # be updated.
    OperationType.AGENT_REQUEST: ObservationType.USER_PROMPT_SUBMITTED,
    OperationType.TOOL_USE: ObservationType.TOOL_EXECUTION_COMPLETED,
    OperationType.TOOL_EXECUTION: ObservationType.TOOL_EXECUTION_COMPLETED,
    # Lane 1 only, and each for its own stated reason:
    #
    # MESSAGE_RESPONSE is one LLM reply. The agent's own stream already writes
    # that turn's tokens to the observation lane as `token_usage`, and
    # `TimescaleSessionCostQuery` prices what it finds there - so a second copy
    # would not add an operation, it would double the session's cost. Its value
    # reaches the API through Lane 1 instead (`SessionListProjection` ->
    # `_lane1_tokens`), which is why `total_tokens` is already right.
    #
    # This entry used to be the ENTIRE production surface of this handler:
    # `complete_success` recorded its end-of-phase roll-up under this name, so
    # every real call landed here and returned without writing anything, and
    # the observation write below was reachable only from tests (#1034, second
    # pass). The roll-up now has its own name - SESSION_COMPLETED, above - and
    # this entry means what it says again.
    OperationType.MESSAGE_RESPONSE: None,
    # The terminal row for a phase that ended well - the counterpart of the
    # `session_error` that `SessionLifecycleManager._record_terminal_status`
    # already writes when it ends badly. `session_completed` is priced by
    # nothing (`TimescaleSessionCostQuery` reads `session_summary`, falling
    # back to `token_usage`) and excluded by nothing (`TIMELINE_EXCLUDE` is
    # `token_usage`, `cost_recorded`, `session_summary`), so it is readable at
    # `GET /sessions/{id}` without touching what the session costs.
    OperationType.SESSION_COMPLETED: ObservationType.SESSION_COMPLETED,
    # THINKING and VALIDATION have no name on the observation lane at all.
    # `ObservationType` is constrained by `syn_shared.events.VALID_EVENT_TYPES`,
    # which gates the write, so giving these two a timeline row needs a new
    # shared constant first. Mapping them onto a type that means something else
    # would put a lie in the timeline, which is worse than the gap.
    OperationType.THINKING: None,
    OperationType.VALIDATION: None,
}


def _observation_type(operation_type: OperationType) -> ObservationType | None:
    """The observation lane's name for this kind of operation, if it has one."""
    if operation_type not in _OBSERVATION_TYPES:
        msg = (
            f"OperationType.{operation_type.name} has no entry in _OBSERVATION_TYPES. "
            "Every operation type must state whether it reaches the session "
            "timeline, so that an omission cannot read as a decision."
        )
        raise ValueError(msg)
    return _OBSERVATION_TYPES[operation_type]


def _preview(value: object) -> str | None:
    """A displayable, length-capped rendering of a tool's input or output."""
    if value is None:
        return None
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    return text[:_MAX_PREVIEW_LEN]


def _observation_data(command: RecordOperationCommand, operation_id: str) -> dict[str, Any]:
    """The timeline row's payload, in the keys its reader already looks for.

    Field names match what ``ObservabilityCollector`` writes for the same kinds
    of observation, because ``session_tools`` reads both through one converter.
    """
    duration = command.duration_seconds
    return {
        "observation_id": operation_id,
        "tool_name": command.tool_name or "",
        "tool_use_id": command.tool_use_id,
        "success": command.success,
        "input_preview": _preview(command.tool_input or command.message_content),
        "output_preview": _preview(command.tool_output),
        "duration_ms": None if duration is None else int(duration * 1000),
    }


@dataclass(frozen=True)
class RecordedOperation:
    """What became of one operation, across both lanes it is written to.

    `handle` returns this because the two writes it makes are not one write.
    The domain write commits to the event store; the timeline write goes to a
    separate observation store, and there is no transaction spanning them, so
    the first can succeed while the second does not. Before this existed the
    second one's exception was caught and logged and nothing else, which meant
    a caller could not tell a healthy session from one whose timeline silently
    lost a row - the disagreement was invisible at exactly the moment it
    mattered (#1034).

    `diverged` is the one question a caller has to ask, and it is deliberately
    narrower than "is this operation on the timeline":

    - the timeline write was attempted and FAILED -> True. The lanes now
      disagree about a session and somebody needs to know.
    - this operation type has no timeline row, or this session has no
      observation lane at all -> False. Both are stated decisions taken
      upfront, not failures, and the caller does not need to know which
      applied - that is the handler's business and it stays there.
    """

    operation_id: str
    """The domain lane's id for the operation. Always written."""

    diverged: bool
    """The domain lane committed this operation and the timeline did not."""

    reason: str | None
    """What went wrong, present exactly when `diverged`."""


class RecordOperationHandler:
    """Handler for RecordOperation command.

    Appends one operation (message, tool lifecycle, thinking, error) to an
    existing session's stream. The aggregate owns every rule about whether
    the operation is admissible - notably that a session which has already
    completed cannot record more - so this handler loads, delegates and
    persists, and decides nothing itself.

    It then puts the same operation on the session's observation lane, because
    that is the lane the read path serves ``operations`` from. Recording only
    the aggregate is what made this handler's writes real and unreadable at the
    same time (#1034): tokens arrived, operations did not.
    """

    def __init__(
        self,
        repository: Repository[AgentSessionAggregate],
        observations: SessionObservationPort | None,
    ) -> None:
        """Initialize handler with its repository and observation lane.

        ``observations`` has no default on purpose. It is the difference
        between an operation that can be read back and one that cannot, and a
        defaulted ``None`` would let a caller lose the read path by omission -
        which is precisely how this handler came to write into a void that
        looked like success. Passing ``None`` is allowed, but it has to be
        typed out: it says "this session has no telemetry lane", and the
        handler says so in the log rather than dropping the write quietly.
        """
        self.repository = repository
        self.observations = observations

    async def handle(self, command: RecordOperationCommand) -> RecordedOperation:
        """Handle operation recording.

        Args:
            command: RecordOperationCommand with operation details

        Returns:
            What became of the operation on both lanes. Check ``diverged``:
            the domain write has committed by the time this returns, so a
            timeline failure is reported here rather than raised.

        Raises:
            ValueError: If no session exists for ``command.aggregate_id``, the
                aggregate rejects the operation, or the operation type has no
                stated position on the timeline.
        """
        session = await self.repository.get_by_id(command.aggregate_id)
        if session is None:
            msg = f"Cannot record operation: session {command.aggregate_id} not found"
            raise ValueError(msg)

        # Resolved before the aggregate is touched: an unmapped operation type
        # is a programming error, and it should not leave a half-recorded
        # session behind it.
        observation_type = _observation_type(command.operation_type)

        session.record_operation(command)
        operation_id = session.operations[-1].operation_id
        await self.repository.save(session)

        return await self._observe(command, session, observation_type, operation_id)

    async def _observe(
        self,
        command: RecordOperationCommand,
        session: AgentSessionAggregate,
        observation_type: ObservationType | None,
        operation_id: str,
    ) -> RecordedOperation:
        """Put the operation where the session read path will find it.

        Never raises, and no longer discards. The domain write has already
        committed by the time this runs, so failing the command afterwards
        would trade a visible operation for a lost one - and Lane 2 must not
        be able to fail a Lane 1 write in any case. A failure is therefore
        reported in the return value AND logged, never swallowed: the log is
        the floor that keeps it from being silent, and the return value is
        what makes it answerable by the caller and assertable by a test.
        """
        if observation_type is None:
            return RecordedOperation(operation_id=operation_id, diverged=False, reason=None)
        if self.observations is None:
            logger.warning(
                "Session %s has no observation lane, so its %s operation will not appear "
                "in GET /sessions/%s operations. The tokens are still recorded.",
                command.aggregate_id,
                command.operation_type.value,
                command.aggregate_id,
            )
            return RecordedOperation(operation_id=operation_id, diverged=False, reason=None)

        try:
            await self.observations.record_observation(
                session_id=command.aggregate_id,
                observation_type=observation_type,
                data=_observation_data(command, operation_id),
                execution_id=session.execution_id,
                phase_id=session.phase_id,
            )
        except Exception as timeline_err:
            logger.exception(
                "Recorded operation %s for session %s in the domain lane but not on the "
                "session timeline; GET /sessions/%s will not show it.",
                operation_id,
                command.aggregate_id,
                command.aggregate_id,
            )
            return RecordedOperation(
                operation_id=operation_id,
                diverged=True,
                reason=f"{type(timeline_err).__name__}: {timeline_err}",
            )
        return RecordedOperation(operation_id=operation_id, diverged=False, reason=None)
