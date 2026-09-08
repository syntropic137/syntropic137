"""One terminal outcome, four sinks, and the same account of why in all of them.

#1205 gave `PhaseFailure` a boundary: it applies itself to its sinks instead of
being unpacked field-by-field by `WorkflowExecutionProcessor._fail_execution`.
That was a MAINTAINABILITY change with no behaviour change, which is the hardest
kind to be sure of - "it still works" was, until this file, asserted by nothing
that would have noticed if it had stopped.

`test_terminal_outcome_boundary.py` pins the boundary from the inside: it calls
`record_in` and `wind_down` on a recording double and asserts what the outcome
asks of a runtime. That is the right test for the decisions the outcome makes.
It is the wrong test for the question here, because it never runs the processor,
and the processor is what does the unpacking that #1205 removed. A `record_in`
that appends the wrong thing and a call site that never calls it are
indistinguishable to it.

So these drive the whole processor into a real failure and read the four sinks
where they are actually CONSUMED:

  1. the run's `phase_results`      - via `record_in`, read off the returned result
  2. the session's `error_message`  - via `wind_down` -> `report_failed`, read off
                                      the `SessionCompletedEvent` the repository stored
  3. the aggregate's failure event  - via `as_command`, read off the stored
                                      `WorkflowFailedEvent`
  4. the caller's result            - via `execution_result`, the return value

That is deliberately the far end of every hop. A value computed correctly by
`PhaseFailure` and dropped one call later - at a constructor that does not
forward it, or a call site that stops calling - is the defect class this file
exists to catch, and it is invisible to a test that asserts on `PhaseFailure`
itself.

WHAT MAKES THE FIXTURE REPRESENTATIVE
The run is TWO phases, the first completing and the second failing. A one-phase
run cannot distinguish the properties that matter:

  - `completed_phases` (1) from `total_phases` (2), and neither from zero;
  - `record_in` APPENDING to the run's results from it replacing them - with one
    phase, `append` and `= [result]` produce the same list;
  - the failure's session from every session, since `report_failed` closes only
    what is still open and phase one's is already closed.

THE LOAD-BEARING ASSERTION is that the reason is byte-identical in all four.
#1196 is what it looks like when it is not: each sink spelled the description
itself, so they went blank together, and nothing downstream could attribute the
difference. The reason's exact prose is NOT asserted - it is #1200's to change -
but that all four carry the same bytes of it is not.
"""

from __future__ import annotations

import dataclasses
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, TypeVar, cast

import pytest
from pydantic import BaseModel

from syn_adapters.projection_stores.memory_store import InMemoryProjectionStore
from syn_adapters.workspace_backends.service import WorkspaceBackend, WorkspaceService
from syn_domain.contexts.agent_sessions._shared.value_objects import SessionStatus
from syn_domain.contexts.agent_sessions.domain.events.SessionCompletedEvent import (
    SessionCompletedEvent,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    AgentConfiguration,
    ExecutablePhase,
    PhaseStatus,
)
from syn_domain.contexts.orchestration.domain.events.WorkflowFailedEvent import WorkflowFailedEvent
from syn_domain.contexts.orchestration.slices.execute_workflow import phase_outcome
from syn_domain.contexts.orchestration.slices.execute_workflow.WorkflowExecutionProcessor import (
    WorkflowExecutionProcessor,
)
from syn_domain.contexts.orchestration.slices.execution_todo.projection import (
    ExecutionTodoProjection,
)
from syn_domain.testing.fake_agent_handler import FakeAgentExecutionHandler
from syn_shared.agents import AgentRunner

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from syn_adapters.workspace_backends.service.managed_workspace import ManagedWorkspace
    from syn_domain.contexts.agent_sessions.domain.aggregate_session.AgentSessionAggregate import (
        AgentSessionAggregate,
    )
    from syn_domain.contexts.agent_sessions.domain.events.agent_observation import (
        ObservationType,
    )
    from syn_domain.contexts.orchestration import AgentExecutionResult
    from syn_domain.contexts.orchestration._shared.TodoValueObjects import TodoItem
    from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
        WorkflowExecutionAggregate,
    )
    from syn_domain.contexts.orchestration.slices.execute_workflow.agent_launch_observation import (
        AgentLaunchObserver,
    )
    from syn_domain.contexts.orchestration.slices.execute_workflow.ObservabilityCollector import (
        ObservabilityCollector,
    )
    from syn_domain.contexts.orchestration.slices.execute_workflow.processor_types import (
        Runner,
        WorkflowExecutionResult,
    )

pytestmark = pytest.mark.unit

_Event = TypeVar("_Event")

FIRST = "phase-001"
FAILED_PHASE = "phase-002"


class _AfterOneGoodPhase(FakeAgentExecutionHandler):
    """A run whose first phase succeeds and whose second ends some other way.

    Subclassed rather than rewritten so the run still goes through the real
    double - and so the Protocol assertion that guards `handle`'s signature keeps
    guarding this too. `FakeAgentExecutionHandler` takes one outcome for the whole
    run, and a run where NO phase completes cannot show `completed_phases` being
    anything but zero, nor carry a completed `PhaseResult` into what the terminal
    outcome reports. Both terminal paths need that, which is why the turn is here
    and only what it turns into is below.
    """

    def _turn(self) -> None:
        """Make every later phase end the way this handler is named for."""
        raise NotImplementedError

    async def handle(
        self,
        todo: TodoItem,
        workspace: ManagedWorkspace,
        agent_env: dict[str, str],
        claude_cmd: list[str],
        session_id: str,
        agent_model: str | None,
        timeout_seconds: int,
        collector: ObservabilityCollector | None = None,
        runner: Runner = AgentRunner.CLAUDE,
        on_launch: AgentLaunchObserver | None = None,
    ) -> AgentExecutionResult:
        if self.calls:
            self._turn()
        return await super().handle(
            todo,
            workspace,
            agent_env,
            claude_cmd,
            session_id,
            agent_model,
            timeout_seconds,
            collector,
            runner,
            on_launch,
        )


class _SecondPhaseFails(_AfterOneGoodPhase):
    """First phase exits 0, every later one exits non-zero."""

    def _turn(self) -> None:
        self._exit_code = 1


class _SecondPhaseCancels(_AfterOneGoodPhase):
    """First phase exits 0, every later one reports the interrupt a cancel sends.

    The cancellation half of the pair, and the reason it exists is what the
    snapshot below could not otherwise see: a run cancelled during its FIRST
    phase reports `phase_results == []`, and `ExecutionMetrics.from_results([])`
    is indistinguishable from `ExecutionMetrics()`. Three of the cancellation
    result's fields were pinned at values no change to `CancelledExecution`
    could move. One completed phase first is what makes them carry something.
    """

    def _turn(self) -> None:
        self._interrupt = True


class _RecordingExecutionRepository:
    """Stores executions and keeps every event they emitted, in order.

    Clears `_uncommitted_events` after each save exactly as the real SDK
    repository does; without that, `ExecutionJournal.append` re-processes events
    on the next save and the recorded list doubles up.
    """

    def __init__(self) -> None:
        self.events: list[object] = []
        self._aggregates: dict[str, WorkflowExecutionAggregate] = {}

    async def save(self, aggregate: WorkflowExecutionAggregate) -> None:
        self.events.extend(envelope.event for envelope in aggregate._uncommitted_events)
        self._aggregates[aggregate.id] = aggregate
        aggregate._uncommitted_events.clear()

    async def save_new(self, aggregate: WorkflowExecutionAggregate) -> None:
        await self.save(aggregate)

    async def get_by_id(self, aggregate_id: str) -> WorkflowExecutionAggregate | None:
        return self._aggregates.get(aggregate_id)


class _RecordingSessionRepository:
    """The session sink. Sessions are only ever saved, never read back."""

    def __init__(self) -> None:
        self.events: list[object] = []

    async def save(self, aggregate: AgentSessionAggregate) -> None:
        self.events.extend(envelope.event for envelope in aggregate._uncommitted_events)
        aggregate._uncommitted_events.clear()


class _SilentArtifactRepository:
    """Artifacts are not a sink of the failure; this keeps the run wired."""

    async def save(self, aggregate: object) -> None:
        return None

    async def get_by_id(self, aggregate_id: str) -> None:
        return None


@dataclass(frozen=True)
class _Observation:
    """One call to the observability recorder, every argument of it kept.

    A frozen dataclass rather than a tuple so the snapshot below names the
    arguments: an observation that started arriving with `phase_id=None` is a
    real regression and a positional capture would only say that "the third
    field" changed.
    """

    session_id: str
    observation_type: ObservationType | str
    data: dict[str, str | None]
    """The payload, with its value type stated rather than erased to `Any`.

    `_record_terminal_status` is the only thing that writes a `session_error`,
    and it writes three values: two strings and a `ModelAlias`, which is a
    `StrEnum` and so is one as well. Nothing here depends on that being the
    only shape - `_canonical` renders whatever arrives - but a test double that
    declares `dict[str, Any]` has described nothing, and this one can say what
    it holds."""
    execution_id: str | None
    phase_id: str | None
    workspace_id: str | None


class _RecordingObservabilityWriter:
    """The observability lane, kept in order. Sink 2's other half.

    `wind_down` -> `report_failed` -> `complete_failure` writes twice: a domain
    event on the session aggregate, and a `session_error` observation that is the
    only trace a run leaves for the dashboard when its agent never produced any
    telemetry of its own. `#1196` was that observation arriving blank, so it is
    the half of sink 2 the fix was actually about, and leaving it unwired would
    leave the test blind to it.
    """

    def __init__(self) -> None:
        self.observations: list[_Observation] = []

    async def record_observation(
        self,
        session_id: str,
        observation_type: ObservationType | str,
        data: dict[str, str | None],
        execution_id: str | None = None,
        phase_id: str | None = None,
        workspace_id: str | None = None,
    ) -> None:
        self.observations.append(
            _Observation(
                session_id=session_id,
                # Kept as it arrived rather than str()-ed: the recorder accepts an
                # enum or a bare string, and flattening one into the other here
                # would hide a sink that swapped which it sends.
                observation_type=observation_type,
                data=dict(data),
                execution_id=execution_id,
                phase_id=phase_id,
                workspace_id=workspace_id,
            )
        )


async def _prompt(
    phase: ExecutablePhase,
    execution_id: str,
    workflow_id: str,
    repo_url: str | None,
    phase_outputs: dict[str, str],
    # `object` rather than the alias's own `dict[str, Any]`: this builder reads
    # none of its arguments, and widening an ignored parameter is sound for a
    # callback. Spelling it `dict[str, Any]` to mirror the alias would have added
    # to the untyped-dict ratchet to say nothing.
    inputs: object,
) -> str:
    return "prompt"


def _command(phase: ExecutablePhase, prompt: str) -> list[str]:
    return ["echo", "agent"]


def _phase(phase_id: str, order: int, name: str) -> ExecutablePhase:
    """A phase declaring NO output, so the #1167 gate is not what fails the run.

    These tests are about what a failure reports, not about which failure it is.
    A declared-but-unproduced output would fail phase one too and cost the run
    its completed phase.
    """
    return ExecutablePhase(
        phase_id=phase_id,
        name=name,
        order=order,
        description="Phase for terminal-outcome coverage",
        agent_config=AgentConfiguration(),
        prompt_template="do the thing",
        output_artifact_types=(),
        timeout_seconds=30,
    )


class _Sinks:
    """One run's four sinks, read where each is consumed."""

    def __init__(
        self,
        result: WorkflowExecutionResult,
        execution_events: list[object],
        session_events: list[object],
        observations: list[_Observation],
    ) -> None:
        self.result = result
        self.execution_events = execution_events
        self.session_events = session_events
        self.observations = observations

    @staticmethod
    def _of_type(events: Sequence[object], event_type: type[_Event]) -> list[_Event]:
        return [event for event in events if isinstance(event, event_type)]

    @property
    def failure_event(self) -> WorkflowFailedEvent:
        """The single `WorkflowFailedEvent` the aggregate stored - sink 3."""
        events = self._of_type(self.execution_events, WorkflowFailedEvent)
        assert len(events) == 1, f"Expected exactly one WorkflowFailedEvent, got {len(events)}"
        return events[0]

    @property
    def completed_sessions(self) -> list[SessionCompletedEvent]:
        """Every `SessionCompletedEvent`, in the order the sessions closed - sink 2."""
        return self._of_type(self.session_events, SessionCompletedEvent)


async def _run(handler: FakeAgentExecutionHandler, execution_id: str) -> _Sinks:
    """Drive the full processor over two phases and collect what it wrote."""
    execution_repository = _RecordingExecutionRepository()
    session_repository = _RecordingSessionRepository()
    observability = _RecordingObservabilityWriter()
    processor = WorkflowExecutionProcessor(
        execution_repository=execution_repository,  # type: ignore[arg-type]
        session_repository=session_repository,  # type: ignore[arg-type]
        workspace_service=WorkspaceService.create(backend=WorkspaceBackend.MEMORY),
        artifact_repository=_SilentArtifactRepository(),  # type: ignore[arg-type]
        artifact_content_storage=None,
        artifact_query=None,
        conversation_storage=None,
        observability_writer=observability,
        controller=None,
        prompt_builder=_prompt,
        command_builder=_command,
        todo_projection=ExecutionTodoProjection(store=InMemoryProjectionStore()),
        agent_handler=handler,
    )
    result = await processor.run(
        workflow_id="wf-1205",
        workflow_name="Terminal Outcome Workflow",
        phases=[_phase(FIRST, 1, "First"), _phase(FAILED_PHASE, 2, "Second")],
        inputs={},
        execution_id=execution_id,
    )
    return _Sinks(
        result,
        execution_repository.events,
        session_repository.events,
        observability.observations,
    )


async def _failed_run(execution_id: str) -> _Sinks:
    return await _run(_SecondPhaseFails(), execution_id)


# ---------------------------------------------------------------------------
# The four sinks
# ---------------------------------------------------------------------------


async def test_all_four_sinks_carry_the_same_account_of_why() -> None:
    """THE load-bearing assertion: one failure, one reason, four identical copies.

    Each sink used to spell the description itself, which is how they came to
    disagree - #1196 is one of them arriving blank while the others did not.
    The boundary exists so the reason is decided once; this is the only test
    that would notice if a sink started deciding it again.

    Compared byte-for-byte against the phase result's copy rather than against a
    literal: the prose is #1200's to change, the agreement is not.
    """
    sinks = await _failed_run("exec-1205-same-reason")

    reason = sinks.result.phase_results[1].error_message
    assert reason, "The failed phase reported no reason at all - that is #1196 exactly."
    # Could not have arisen by default: names the phase that failed and its exit code.
    assert FAILED_PHASE in reason
    assert "exit_code=1" in reason

    assert sinks.result.error_message == reason, "The caller's result disagrees (sink 4)."
    assert sinks.failure_event.error_message == reason, "The stored event disagrees (sink 3)."
    failed_sessions = [s for s in sinks.completed_sessions if s.status == SessionStatus.FAILED]
    assert [s.error_message for s in failed_sessions] == [reason], (
        "The closed session disagrees (sink 2)."
    )


async def test_the_failed_phase_is_appended_to_the_phases_that_preceded_it() -> None:
    """SINK 1. `record_in` adds the failure's phase; it does not become the list.

    The order and the length are the assertions. A `record_in` that replaced the
    run's results would lose the completed phase - and with it the run's token
    totals and its `completed_phases` count - while still leaving a plausible
    failed phase at index 0.
    """
    sinks = await _failed_run("exec-1205-appended")

    assert [r.phase_id for r in sinks.result.phase_results] == [FIRST, FAILED_PHASE]
    completed, failed = sinks.result.phase_results
    assert completed.status == PhaseStatus.COMPLETED
    assert completed.error_message is None, "The completed phase inherited the failure's reason."
    assert failed.status == PhaseStatus.FAILED
    # Read before teardown or not at all: `abandon_all` empties the map this came
    # from, so a failure that read it afterwards reports "" here (#1036).
    assert failed.session_id, "The failed phase lost its session id."
    assert failed.session_id != completed.session_id


async def test_only_the_still_open_session_is_closed_as_failed() -> None:
    """SINK 2. `wind_down` closes what the failure ends - not the run's history.

    Both sessions are closed by the time the run returns, but for different
    reasons and with different verbs: phase one's completed when phase one did.
    A `wind_down` that reached every session the run ever opened would rewrite a
    successful phase as a failed one, and only the count here would say so.
    """
    sinks = await _failed_run("exec-1205-open-session")

    statuses = [s.status for s in sinks.completed_sessions]
    assert statuses == [SessionStatus.COMPLETED, SessionStatus.FAILED], (
        f"Expected the first phase's session to close completed and the second's "
        f"to close failed, got {statuses}."
    )
    assert sinks.completed_sessions[0].error_message is None
    assert sinks.completed_sessions[1].session_id == sinks.result.phase_results[1].session_id, (
        "The session closed as failed is not the one the failed phase ran under."
    )


async def test_the_aggregate_is_told_which_phase_failed_and_how_far_the_run_got() -> None:
    """SINK 3. Every field `as_command` fills, read off the event that stored it.

    `completed_phases` and `total_phases` are 1 and 2 rather than 0 and 1: they
    are different numbers, neither is a zero, and swapping them is visible.
    `observed_branches` is `[]` and NOT None - the difference between "git was
    read and nothing had moved" and "nobody could look" is the whole of #1200,
    and None is what a call site that stopped passing it would produce.
    """
    sinks = await _failed_run("exec-1205-command")

    event = sinks.failure_event
    assert event.failed_phase_id == FAILED_PHASE, (
        f"The failure was attributed to {event.failed_phase_id!r}. Naming the "
        "completed phase, or naming none, is how a run points a reader at the "
        "wrong place entirely."
    )
    assert event.error_type == "RuntimeError", (
        f"Expected the type of the exception that ended the run, got {event.error_type!r}."
    )
    assert event.completed_phases == 1
    assert event.total_phases == 2
    assert event.observed_branches == [], (
        f"Expected [] - read, and nothing had moved - got {event.observed_branches!r}. "
        "None here means the observation never reached the aggregate (#1200)."
    )


async def test_the_caller_is_handed_a_failed_result_that_counts_both_phases() -> None:
    """SINK 4. The return value, including the metrics derived from sink 1.

    The metrics are the reason sink 1 and sink 4 cannot be checked apart: they
    are computed FROM the phase results `record_in` built, so a failure that
    recorded nothing would return `failed_phases=0` - a failed run reporting no
    failed phase, which every dashboard downstream believes.
    """
    sinks = await _failed_run("exec-1205-result")

    assert sinks.result.status == "failed"
    assert sinks.result.workflow_id == "wf-1205"
    assert sinks.result.execution_id == "exec-1205-result"
    assert sinks.result.metrics.total_phases == 2
    assert sinks.result.metrics.completed_phases == 1
    assert sinks.result.metrics.failed_phases == 1


async def test_the_failed_phase_is_timed_by_its_own_clock_reading() -> None:
    """The cross-sink relation, and the one that no single sink can state.

    `failed_phase_duration_seconds` on the event and the failed `PhaseResult`'s
    own elapsed time are the SAME number because `failed_phase_outcome` reads the
    clock once and hands that instant to both. Two readings would put two
    durations on one phase, and each would look right where it was read.

    Equality is exact, not approximate: these are not two measurements that agree
    closely, they are one measurement used twice. And it is non-zero, which is
    the #1036 property - a failed phase used to report 0.0 because nothing on the
    failure path computed a duration at all.
    """
    sinks = await _failed_run("exec-1205-duration")

    failed = sinks.result.phase_results[1]
    assert failed.started_at is not None
    assert failed.completed_at is not None
    elapsed = (failed.completed_at - failed.started_at).total_seconds()
    assert elapsed > 0.0, "The failed phase reports no duration at all (#1036)."
    assert sinks.failure_event.failed_phase_duration_seconds == elapsed, (
        f"The event says {sinks.failure_event.failed_phase_duration_seconds} and the "
        f"phase result says {elapsed}. One failure, one clock reading."
    )


# ---------------------------------------------------------------------------
# The sibling outcome, fixed in the same commit and unpinned for the same reason
# ---------------------------------------------------------------------------


async def test_a_cancelled_run_closes_its_session_with_the_reason_it_reports() -> None:
    """`CancelledExecution` was unpacked at the call site the same way.

    It has three sinks rather than four - the aggregate is already CANCELLED by
    the time the to-do list empties, so there is no command - and the same
    property has to hold across them: the reason the caller is handed is the
    reason the sessions were closed with. The call site used to pick the verb and
    read `reason` back out to hand to it, which is how one resolved default came
    to be spelled in one place and used in another.
    """
    sinks = await _run(FakeAgentExecutionHandler.cancelled(), "exec-1205-cancelled")

    assert sinks.result.status == "cancelled"
    reason = sinks.result.error_message
    assert reason, "A cancelled run reported no reason."
    cancelled = [s for s in sinks.completed_sessions if s.status == SessionStatus.CANCELLED]
    assert [s.error_message for s in cancelled] == [reason], (
        "The session was closed with a different reason than the caller was given."
    )


# ---------------------------------------------------------------------------
# The whole of every sink, against what the sinks held before #1205
# ---------------------------------------------------------------------------
#
# Everything above asserts SELECTED properties, which is the right shape for
# saying what matters and why. It is the wrong shape for the claim #1205 makes.
# "Nothing changed" is not a property of a few named fields; it is a property of
# the entire output, and a named-field assertion is silent about every field it
# does not name - a `metadata` key that appeared, an `artifact_id` that stopped
# being None, a token count that started arriving from somewhere else. Those are
# exactly what a refactor drops, and exactly what nothing above would notice.
#
# So the rest of this file captures ALL of every sink and compares the whole
# thing. The two mechanisms that make that mean something:
#
#   COMPLETENESS is structural, not a list. `_canonical` reads fields off the
#   type - `model_fields` for events, `dataclasses.fields` for value objects,
#   every key of every dict - so a field ADDED to any sink appears in the
#   snapshot with no edit here, and a field REMOVED disappears from it. Either
#   one fails the comparison. There is no list of fields to keep in step,
#   because a list is the thing that goes stale.
#
#   THE EXPECTATION IS NOT OURS. It was produced by running this same harness
#   against the tree with 1b8c259a reverted - the code as it stood BEFORE the
#   refactor - and is committed beside this file. Deriving it from the current
#   implementation would produce a test that agrees with whatever the refactor
#   did, which is the one thing it must not do. `_write_golden` refuses to run
#   at all on a tree where the refactor is present, so that cannot be done by
#   accident later either.

_FAILURE_GOLDEN = Path(__file__).with_name("terminal_failure_prerefactor_golden.json")
_CANCELLATION_GOLDEN = Path(__file__).with_name("terminal_cancellation_prerefactor_golden.json")

REGENERATE_ENV = "SYN_1205_WRITE_PREREFACTOR_GOLDEN"
"""Set to "1" to rewrite the goldens. See `_before_the_refactor` for the terms."""

_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")

type _Leaf = str | int | float | bool | None
"""A value that survives a JSON round trip unchanged, so the golden can hold it."""

type _Canonical = _Leaf | dict[str, _Canonical] | list[_Canonical]
"""A sink rendered as data: leaves, and the two containers they nest in."""

type _Snapshot = dict[str, _Leaf]
"""A whole run's sinks as path -> leaf. See `_flatten` for why it is flat."""


class _PerRunEntropy:
    """Stable stand-ins for the values no two runs can agree on.

    A uuid and a wall-clock reading differ between any two runs of any two
    checkouts, so pinning them literally would pin the machine and not the code.
    Each DISTINCT value gets a token instead, numbered in the order the walk
    first meets it, and that keeps precisely what the refactor could have broken:

      - WHICH fields carry an id or an instant at all (a field that stopped
        being filled holds None, not a token, and the comparison says so);
      - WHETHER two fields carry the SAME one. The failed phase's session id
        appears in three sinks and the failure's single clock reading appears in
        two, and both are one token everywhere they appear. A sink that started
        reading its own clock, or reaching for a different session, gets a
        different token and fails - and that cross-sink agreement is asserted
        here by the structure rather than by remembering to write it down.

    Zero is not entropy and is never tokenised: `0.0` is what a failed phase's
    duration used to be when nothing computed it (#1036), so "no time at all"
    and "some time" have to stay different values in the snapshot.
    """

    def __init__(self) -> None:
        self._tokens: dict[tuple[str, object], str] = {}
        self._counts: dict[str, int] = {}

    def token(self, kind: str, value: object) -> str:
        key = (kind, value)
        token = self._tokens.get(key)
        if token is None:
            token = f"<{kind}-{self._counts.get(kind, 0)}>"
            self._tokens[key] = token
            self._counts[kind] = self._counts.get(kind, 0) + 1
        return token


def _canonical(value: object, entropy: _PerRunEntropy) -> _Canonical:
    """One sink value as comparable data, with nothing left out.

    Unknown types RAISE rather than falling back to `repr`. A repr fallback is
    how a snapshot test quietly stops covering the field it was added for: the
    value still appears, still differs when it differs, and hides a type change
    behind a string. If this raises, a sink has grown a field holding something
    new and somebody has to decide how it is compared - which is the point.
    """
    if value is None:
        return None
    # BEFORE str and int, both of which these subclass. A `StrEnum` member caught
    # by the `str` branch would be recorded as its bare value, and a sink that
    # swapped an enum for the string it happens to equal would read as unchanged.
    if isinstance(value, Enum):
        return f"{type(value).__name__}.{value.name}"
    if isinstance(value, bool | int):
        return value
    if isinstance(value, float):
        # See `_PerRunEntropy` on why zero is kept and everything else tokenised.
        return 0.0 if value == 0.0 else entropy.token("seconds", value)
    if isinstance(value, str):
        return _UUID.sub(lambda m: entropy.token("uuid", m.group(0)), value)
    if isinstance(value, datetime):
        return entropy.token("instant", value.isoformat())
    if isinstance(value, BaseModel):
        return _canonical_fields(value, value.__class__.model_fields, entropy)
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return _canonical_fields(value, [f.name for f in dataclasses.fields(value)], entropy)
    if isinstance(value, dict):
        entries = cast("dict[object, object]", value)
        return {str(key): _canonical(entries[key], entropy) for key in sorted(entries, key=str)}
    if isinstance(value, list):
        return [_canonical(item, entropy) for item in cast("list[object]", value)]
    msg = (
        f"A sink now holds a {type(value).__name__}, which this snapshot does not "
        "know how to compare. Decide how it should be compared and teach "
        "`_canonical` - do not let it fall back to a string."
    )
    raise TypeError(msg)


def _canonical_fields(
    value: object, field_names: Iterable[str], entropy: _PerRunEntropy
) -> dict[str, _Canonical]:
    """Every declared field of one object, plus the type that declared them.

    `__type__` is carried because a sink whose value object was swapped for a
    look-alike with the same fields is a change, and one the field values alone
    cannot show.
    """
    canonical: dict[str, _Canonical] = {"__type__": type(value).__name__}
    for name in field_names:
        canonical[name] = _canonical(getattr(value, name), entropy)
    return canonical


def _flatten(value: _Canonical, path: str = "") -> _Snapshot:
    """The canonical form as one flat path -> leaf mapping.

    Flat because that is what makes a failure readable: comparing two nested
    structures reports that they differ, comparing two flat mappings reports
    WHICH PATH differs, and pytest prints the paths present in one and not the
    other - which is what "a field disappeared" looks like from here.

    Empty containers get a leaf of their own. Without one, a field holding `[]`
    and a field that is not there at all would flatten to the same thing -
    nothing - and "the artifact ids stopped being reported" would pass.
    """
    if isinstance(value, dict):
        if not value:
            return {path: "{}"}
        flat: _Snapshot = {}
        for key, item in value.items():
            flat.update(_flatten(item, f"{path}/{key}"))
        return flat
    if isinstance(value, list):
        if not value:
            return {path: "[]"}
        flat = {}
        for index, item in enumerate(value):
            flat.update(_flatten(item, f"{path}[{index}]"))
        return flat
    return {path: value}


def _snapshot(**sinks: object) -> _Snapshot:
    """The named sinks of one run, canonicalised against ONE entropy map.

    One map across all of them is what makes the cross-sink identities visible:
    the same session id read by three sinks is the same token in all three, so a
    sink that started reaching for a different one shows up as a token mismatch
    rather than as two unrelated uuids that were never compared. Snapshotting
    each sink separately would lose exactly that.
    """
    return _flatten(_canonical(sinks, _PerRunEntropy()))


def _failure_snapshot(sinks: _Sinks) -> _Snapshot:
    """All four sinks `PhaseFailure` writes to."""
    return _snapshot(
        sink1_phase_results=sinks.result.phase_results,
        sink2_session_error_observations=sinks.observations,
        sink2_session_completed_events=sinks.completed_sessions,
        sink3_stored_failure_event=sinks.failure_event,
        sink4_execution_result=sinks.result,
    )


def _cancellation_snapshot(sinks: _Sinks) -> _Snapshot:
    """The three sinks `CancelledExecution` writes to.

    Three rather than four for the reason the test below its sibling gives: the
    aggregate is already CANCELLED when the to-do list empties, so nothing
    corresponding to `as_command` is ever built. The stored
    `ExecutionCancelledEvent` is deliberately NOT here - it is the cancel
    command's, written before teardown begins, and pinning it would pin
    machinery this outcome does not own.
    """
    return _snapshot(
        sink1_phase_results=sinks.result.phase_results,
        sink2_session_error_observations=sinks.observations,
        sink2_session_completed_events=sinks.completed_sessions,
        sink3_execution_result=sinks.result,
    )


def _describe(actual: _Snapshot, expected: _Snapshot) -> str:
    """What differs, as paths - the message a reader gets at 2am."""
    lines: list[str] = []
    for path in sorted(set(expected) - set(actual)):
        lines.append(f"  GONE     {path}: was {expected[path]!r}")
    for path in sorted(set(actual) - set(expected)):
        lines.append(f"  NEW      {path}: now {actual[path]!r}")
    for path in sorted(set(actual) & set(expected)):
        if actual[path] != expected[path]:
            lines.append(f"  CHANGED  {path}: was {expected[path]!r}, now {actual[path]!r}")
    return "\n".join(lines)


def _before_the_refactor(golden: Path, snapshot: _Snapshot) -> _Snapshot:
    """What these sinks held before #1205, to compare `snapshot` against.

    Normally this just reads the committed file. With `REGENERATE_ENV` set it
    rewrites it first - and REFUSES to unless `PhaseFailure.record_in` and
    `CancelledExecution.wind_down` are both absent, which is to say unless
    1b8c259a is not applied to the tree it is running on.

    THAT REFUSAL IS THE WHOLE MECHANISM. An expectation taken from the current
    implementation asserts that the code does what the code does. It is green,
    it looks like coverage, and it says nothing whatsoever about whether the
    refactor changed behaviour - which is the only question these two tests
    exist to answer. Making that impossible to do by accident is worth more
    than a comment asking people not to.

    To regenerate::

        git worktree add --detach /tmp/pre-1205 HEAD
        git -C /tmp/pre-1205 revert --no-commit --no-edit 1b8c259a
        cp <this file> /tmp/pre-1205/<same path>
        cd /tmp/pre-1205 && SYN_1205_WRITE_PREREFACTOR_GOLDEN=1 uv run pytest <that file>
        cp /tmp/pre-1205/<goldens> <here>
    """
    if os.environ.get(REGENERATE_ENV) == "1":
        for owner, method in (("PhaseFailure", "record_in"), ("CancelledExecution", "wind_down")):
            if hasattr(getattr(phase_outcome, owner), method):
                msg = (
                    f"Refusing to write {golden.name}: {owner}.{method} exists, so this "
                    "tree HAS #1205's refactor applied. An expectation taken from it "
                    "would agree with the refactor by construction and prove nothing. "
                    "Revert 1b8c259a first - see this function's docstring."
                )
                raise AssertionError(msg)
        golden.write_text(json.dumps(snapshot, indent=2, sort_keys=True) + "\n")
    expected: _Snapshot = json.loads(golden.read_text())
    return expected


async def test_every_sink_holds_exactly_what_it_held_before_the_refactor() -> None:
    """The whole of all four sinks, against the tree that predates #1205.

    This is the only assertion in this file that can fail for a reason nobody
    thought of in advance, which is the reason it exists. The tests above encode
    what somebody knew to look for; a refactor's risk is the field nobody
    thought to look at.

    A failure here is NOT automatically a bug - a later change may legitimately
    alter one of these sinks. It is a claim that #1205's "byte-identical" no
    longer holds, and the paths in the message say where. Read them, decide
    whether the change was meant, and if it was, regenerate as `_write_golden`
    describes.
    """
    snapshot = _failure_snapshot(await _failed_run("exec-1205-golden"))

    expected = _before_the_refactor(_FAILURE_GOLDEN, snapshot)
    assert snapshot == expected, (
        "A failure sink no longer holds what it held before #1205 was applied:\n"
        + _describe(snapshot, expected)
    )


async def test_a_cancelled_run_holds_exactly_what_it_held_before_the_refactor() -> None:
    """The same whole-output comparison for the sibling outcome.

    `CancelledExecution` was unpacked at its call site the same way and moved in
    the same commit, so it carries the same risk and had the same coverage gap:
    the test above it names `status` and one reason and is silent about
    everything else the cancellation reports. A cancelled run's sinks are pinned
    here for exactly the reason the failure's are.

    The run cancels its SECOND phase rather than its first, so the completed
    first phase is in `phase_results` and the metrics derived from it are not
    the ones an empty run would produce. Cancelling immediately - which is what
    the test above it does - pins `phase_results`, `artifact_ids` and `metrics`
    at values that no change to `CancelledExecution` could move, and a field
    that cannot differ is not covered by a comparison that includes it.

    `artifact_ids` is `[]` here even so, because this run produces none, and
    `[]` is a different fact from "the field is gone" - `_flatten` gives an
    empty container a leaf of its own so the two cannot be confused.
    """
    snapshot = _cancellation_snapshot(
        await _run(_SecondPhaseCancels(), "exec-1205-cancelled-golden")
    )

    expected = _before_the_refactor(_CANCELLATION_GOLDEN, snapshot)
    assert snapshot == expected, (
        "A cancellation sink no longer holds what it held before #1205 was applied:\n"
        + _describe(snapshot, expected)
    )
