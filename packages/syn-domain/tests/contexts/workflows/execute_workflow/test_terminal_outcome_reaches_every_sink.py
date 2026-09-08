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

from typing import TYPE_CHECKING, TypeVar

import pytest

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
from syn_domain.contexts.orchestration.slices.execute_workflow.WorkflowExecutionProcessor import (
    WorkflowExecutionProcessor,
)
from syn_domain.contexts.orchestration.slices.execution_todo.projection import (
    ExecutionTodoProjection,
)
from syn_domain.testing.fake_agent_handler import FakeAgentExecutionHandler

if TYPE_CHECKING:
    from collections.abc import Sequence

    from syn_adapters.workspace_backends.service.managed_workspace import ManagedWorkspace
    from syn_domain.contexts.agent_sessions.domain.aggregate_session.AgentSessionAggregate import (
        AgentSessionAggregate,
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


class _SecondPhaseFails(FakeAgentExecutionHandler):
    """Exit 0 for the first phase this handler is given, non-zero for the rest.

    Subclassed rather than rewritten so the run still goes through the real
    double - and so the Protocol assertion that guards `handle`'s signature keeps
    guarding this too. `FakeAgentExecutionHandler` takes one exit code for the
    whole run, and a run where every phase fails cannot show `completed_phases`
    being anything but zero.
    """

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
        runner: Runner | None = None,
        on_launch: AgentLaunchObserver | None = None,
    ) -> AgentExecutionResult:
        self._exit_code = 0 if not self.calls else 1
        if runner is None:
            return await super().handle(
                todo,
                workspace,
                agent_env,
                claude_cmd,
                session_id,
                agent_model,
                timeout_seconds,
                collector,
                on_launch=on_launch,
            )
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
    ) -> None:
        self.result = result
        self.execution_events = execution_events
        self.session_events = session_events

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
    processor = WorkflowExecutionProcessor(
        execution_repository=execution_repository,  # type: ignore[arg-type]
        session_repository=session_repository,  # type: ignore[arg-type]
        workspace_service=WorkspaceService.create(backend=WorkspaceBackend.MEMORY),
        artifact_repository=_SilentArtifactRepository(),  # type: ignore[arg-type]
        artifact_content_storage=None,
        artifact_query=None,
        conversation_storage=None,
        observability_writer=None,
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
    return _Sinks(result, execution_repository.events, session_repository.events)


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
