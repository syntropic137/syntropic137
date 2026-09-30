"""The parent's decision to admit a resume (ADR-014 s7).

Every refusal here is asserted against a parent READ BACK FROM ITS STREAM,
not against the object that just handled a command. The rules are only worth
anything if they hold for the aggregate a later request loads - "already
resumed" in particular is a fact that has to survive the process that recorded
it, or the one-resume rule is one resume per restart.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from event_sourcing import DomainEvent, EventEnvelope, GenericDomainEvent

from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    ExecutionStatus,
    FailureClassification,
    InheritedPhase,
    PhaseDefinition,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
    ArtifactsCollectedCommand,
    CancelExecutionCommand,
    CompleteExecutionCommand,
    CompletePhaseCommand,
    FailExecutionCommand,
    InterruptExecutionCommand,
    ResumeExecutionCommand,
    RetryPhaseCommand,
    StartExecutionCommand,
    StartPhaseCommand,
    WorkflowExecutionAggregate,
)
from syn_domain.contexts.orchestration.domain.events.ExecutionResumedEvent import (
    ExecutionResumedEvent,
)
from syn_domain.contexts.orchestration.domain.events.PhaseStartedEvent import (
    PhaseStartedEvent,
)

if TYPE_CHECKING:
    from collections.abc import Callable

PARENT = "exec-parent"
RESUME = "exec-resume"
PHASES = ("research", "plan", "implement")


# --- the parent's history ------------------------------------------------


def _started() -> WorkflowExecutionAggregate:
    aggregate = WorkflowExecutionAggregate()
    aggregate.start_execution(
        StartExecutionCommand(
            execution_id=PARENT,
            workflow_id="wf-1",
            workflow_name="Resume test",
            total_phases=len(PHASES),
            inputs={"task": "resume me"},
            phase_definitions=[
                PhaseDefinition(phase_id=p, name=p.title(), order=i + 1)
                for i, p in enumerate(PHASES)
            ],
        )
    )
    return aggregate


def _start_phase(aggregate: WorkflowExecutionAggregate, phase_id: str) -> None:
    aggregate.start_phase(
        StartPhaseCommand(
            execution_id=PARENT,
            workflow_id="wf-1",
            phase_id=phase_id,
            phase_name=phase_id.title(),
            phase_order=PHASES.index(phase_id) + 1,
        )
    )


def _collect(aggregate: WorkflowExecutionAggregate, phase_id: str, *ids: str) -> None:
    aggregate.artifacts_collected(
        ArtifactsCollectedCommand(execution_id=PARENT, phase_id=phase_id, artifact_ids=list(ids))
    )


def _complete_phase(aggregate: WorkflowExecutionAggregate, phase_id: str) -> None:
    aggregate.complete_phase(
        CompletePhaseCommand(
            execution_id=PARENT,
            workflow_id="wf-1",
            phase_id=phase_id,
            session_id=None,
            artifact_id=None,
            input_tokens=0,
            output_tokens=0,
            cache_creation_tokens=0,
            cache_read_tokens=0,
            total_tokens=0,
            duration_seconds=1.0,
        )
    )


def _run_phase(aggregate: WorkflowExecutionAggregate, phase_id: str, *artifact_ids: str) -> None:
    _start_phase(aggregate, phase_id)
    _collect(aggregate, phase_id, *artifact_ids)
    _complete_phase(aggregate, phase_id)


def _fail(aggregate: WorkflowExecutionAggregate, failed_phase_id: str | None = None) -> None:
    aggregate.fail_execution(
        FailExecutionCommand(
            execution_id=PARENT,
            error="boom",
            error_type="AgentError",
            failed_phase_id=failed_phase_id,
            completed_phases=1,
            total_phases=len(PHASES),
            classification=FailureClassification.UNCLASSIFIED,
        )
    )


def _failed_between_phases() -> WorkflowExecutionAggregate:
    """research done with two artifacts; failed before plan started."""
    aggregate = _started()
    _run_phase(aggregate, "research", "art-research-1", "art-research-2")
    _fail(aggregate)
    return aggregate


def _cancelled_between_phases() -> WorkflowExecutionAggregate:
    aggregate = _started()
    _run_phase(aggregate, "research", "art-research-1")
    aggregate.cancel_execution(
        CancelExecutionCommand(execution_id=PARENT, phase_id="plan", reason="wrong repo")
    )
    return aggregate


def _interrupted_between_phases() -> WorkflowExecutionAggregate:
    aggregate = _started()
    _run_phase(aggregate, "research", "art-research-1")
    aggregate.interrupt_execution(InterruptExecutionCommand(execution_id=PARENT, phase_id="plan"))
    return aggregate


def _completed() -> WorkflowExecutionAggregate:
    aggregate = _started()
    for phase_id in PHASES:
        _run_phase(aggregate, phase_id, f"art-{phase_id}")
    aggregate.complete_execution(
        CompleteExecutionCommand(
            execution_id=PARENT,
            completed_phases=len(PHASES),
            total_phases=len(PHASES),
            total_input_tokens=0,
            total_output_tokens=0,
            total_cache_creation_tokens=0,
            total_cache_read_tokens=0,
            duration_seconds=3.0,
            artifact_ids=[f"art-{p}" for p in PHASES],
        )
    )
    return aggregate


def _running() -> WorkflowExecutionAggregate:
    aggregate = _started()
    _run_phase(aggregate, "research", "art-research-1")
    return aggregate


# --- the store --------------------------------------------------------------


class _Store:
    """The parent's stream as the event store holds it: append-only, and read
    back through JSON into a FRESH aggregate on every load."""

    def __init__(self, history: WorkflowExecutionAggregate) -> None:
        self._events: list[EventEnvelope[DomainEvent]] = []
        self.save(history)

    def save(self, aggregate: WorkflowExecutionAggregate) -> None:
        self._events.extend(
            EventEnvelope(
                event=type(e.event).model_validate_json(e.event.model_dump_json()),
                metadata=e.metadata,
            )
            for e in aggregate.get_uncommitted_events()
        )
        aggregate.mark_events_as_committed()

    def load(self) -> WorkflowExecutionAggregate:
        fresh = WorkflowExecutionAggregate()
        fresh.rehydrate(list(self._events))
        return fresh

    def resumed(self) -> list[ExecutionResumedEvent]:
        return [e.event for e in self._events if isinstance(e.event, ExecutionResumedEvent)]


def _resume(
    store: _Store,
    resume_id: str = RESUME,
    *,
    override_cancellation: bool = False,
    acknowledge_external_effects: bool = False,
) -> None:
    """Load the parent, ask it for a resume, and save whatever it decided."""
    parent = store.load()
    parent.resume_execution(
        ResumeExecutionCommand(
            execution_id=PARENT,
            resume_execution_id=resume_id,
            override_cancellation=override_cancellation,
            acknowledge_external_effects=acknowledge_external_effects,
        )
    )
    store.save(parent)


def _without_resume_id(event: ExecutionResumedEvent) -> GenericDomainEvent:
    """The stored resume event as a stream that lost `resume_execution_id` replays it.

    This is the ADR-023 fallback, built the way the store builds it: typed
    validation fails, so the event comes back as `GenericDomainEvent` carrying
    whatever fields the payload had. Dropping the one field is what makes the
    hazard real - a stand-in that still carried it would exercise nothing.
    """
    payload = event.model_dump()
    payload.pop("resume_execution_id", None)
    return GenericDomainEvent(event_type="ExecutionResumed", **payload)


def _resumed_event(store: _Store) -> ExecutionResumedEvent:
    resumed = store.resumed()
    assert len(resumed) == 1, resumed
    return resumed[0]


# --- tests ------------------------------------------------------------------


@pytest.mark.unit
class TestResumedAtMostOnce:
    def test_a_second_resume_is_refused_by_the_reloaded_parent(self) -> None:
        """A retried request cannot resume the parent twice.

        Each attempt loads the parent from the store, as a separate request
        would, so the refusal comes from the stream and not from an object that
        remembers the first resume.

        What this does NOT prove: safety under two SIMULTANEOUS requests. This
        store appends without optimistic concurrency, so both would read a
        parent that had not yet been resumed and both would pass this guard.
        Genuinely concurrent resumes are refused one layer out, by the
        repository's expected-version check on append, and that belongs to the
        slice that wires one up - not to a fake store that cannot conflict.
        """
        store = _Store(_failed_between_phases())
        _resume(store, "exec-resume-a")

        with pytest.raises(ValueError, match="already been resumed as exec-resume-a"):
            _resume(store, "exec-resume-b")
        assert [e.resume_execution_id for e in store.resumed()] == ["exec-resume-a"]

    def test_the_parent_stays_the_terminal_run_it_was(self) -> None:
        store = _Store(_failed_between_phases())
        _resume(store)

        assert store.load().status is ExecutionStatus.FAILED


@pytest.mark.unit
class TestCancelledParent:
    def test_refused_without_the_override(self) -> None:
        store = _Store(_cancelled_between_phases())
        assert store.load().status is ExecutionStatus.CANCELLED

        with pytest.raises(
            ValueError,
            match="cancelled, and resuming a cancelled execution needs an explicit override",
        ):
            _resume(store)
        assert store.resumed() == []

    def test_refused_when_only_external_effects_are_acknowledged(self) -> None:
        """The two decisions are separate; one does not stand in for the other."""
        store = _Store(_cancelled_between_phases())

        with pytest.raises(ValueError, match="explicit override"):
            _resume(store, acknowledge_external_effects=True)
        assert store.resumed() == []

    def test_accepted_with_the_override_and_says_so(self) -> None:
        store = _Store(_cancelled_between_phases())
        _resume(store, override_cancellation=True)

        resumed = _resumed_event(store)
        assert resumed.resume_execution_id == RESUME
        assert resumed.cancellation_overridden is True

    def test_a_failed_parent_does_not_record_an_override_it_did_not_need(self) -> None:
        store = _Store(_failed_between_phases())
        _resume(store, override_cancellation=True)

        assert _resumed_event(store).cancellation_overridden is False


@pytest.mark.unit
class TestResumableStatuses:
    @pytest.mark.parametrize(
        "history",
        [_failed_between_phases, _interrupted_between_phases],
        ids=["failed", "interrupted"],
    )
    def test_resumable_on_the_request_alone(
        self, history: Callable[[], WorkflowExecutionAggregate]
    ) -> None:
        store = _Store(history())
        _resume(store)

        resumed = _resumed_event(store)
        assert resumed.execution_id == PARENT
        assert resumed.resume_execution_id == RESUME

    @pytest.mark.parametrize(
        ("history", "status"),
        [
            (_completed, ExecutionStatus.COMPLETED),
            (_running, ExecutionStatus.RUNNING),
        ],
        ids=["completed", "running"],
    )
    def test_never_resumable_even_with_both_flags(
        self, history: Callable[[], WorkflowExecutionAggregate], status: ExecutionStatus
    ) -> None:
        store = _Store(history())
        assert store.load().status is status

        with pytest.raises(ValueError, match=f"Cannot resume execution in status {status}"):
            _resume(store, override_cancellation=True, acknowledge_external_effects=True)
        assert store.resumed() == []

    def test_an_execution_that_never_started_is_not_resumable(self) -> None:
        with pytest.raises(ValueError, match="has not been started"):
            WorkflowExecutionAggregate().resume_execution(
                ResumeExecutionCommand(
                    execution_id=PARENT,
                    resume_execution_id=RESUME,
                    override_cancellation=True,
                    acknowledge_external_effects=True,
                )
            )

    def test_a_resume_cannot_reuse_its_parents_id(self) -> None:
        store = _Store(_failed_between_phases())

        with pytest.raises(ValueError, match="execution id of its own"):
            _resume(store, PARENT)


@pytest.mark.unit
class TestInheritedPrefix:
    def test_completed_phases_are_inherited_with_every_collected_artifact(self) -> None:
        store = _Store(_failed_between_phases())
        _resume(store)

        resumed = _resumed_event(store)
        assert resumed.inherited_phases == [
            InheritedPhase(phase_id="research", artifact_ids=["art-research-1", "art-research-2"])
        ]
        assert resumed.resume_phase_id == "plan"

    def test_a_phase_completed_after_a_gap_is_not_inherited(self) -> None:
        """Only the CONTIGUOUS prefix: `implement` completed, `plan` did not.

        A rule that took every completed phase would inherit `implement` and
        resume at `plan`, handing the resume work built on a predecessor it is
        about to redo.
        """
        history = _started()
        _run_phase(history, "research", "art-research")
        _complete_phase(history, "implement")
        _fail(history)
        store = _Store(history)
        _resume(store)

        resumed = _resumed_event(store)
        assert [p.phase_id for p in resumed.inherited_phases] == ["research"]
        assert resumed.resume_phase_id == "plan"

    def test_artifacts_of_an_abandoned_attempt_are_not_inherited(self) -> None:
        history = _started()
        _start_phase(history, "research")
        _collect(history, "research", "art-abandoned")
        history.retry_phase(
            RetryPhaseCommand(execution_id=PARENT, phase_id="research", reason="stream cut")
        )
        _run_phase(history, "research", "art-kept")
        _fail(history)
        store = _Store(history)
        _resume(store)

        assert _resumed_event(store).inherited_phases == [
            InheritedPhase(phase_id="research", artifact_ids=["art-kept"])
        ]

    def test_nothing_completed_inherits_nothing_and_resumes_at_the_first_phase(self) -> None:
        history = _started()
        _fail(history)
        store = _Store(history)
        _resume(store)

        resumed = _resumed_event(store)
        assert resumed.inherited_phases == []
        assert resumed.resume_phase_id == "research"

    def test_a_parent_with_no_unfinished_phase_is_refused(self) -> None:
        history = _started()
        for phase_id in PHASES:
            _run_phase(history, phase_id)
        _fail(history)
        store = _Store(history)

        with pytest.raises(ValueError, match="no unfinished phase"):
            _resume(store)


@pytest.mark.unit
class TestExternalEffects:
    @staticmethod
    def _failed_inside_plan() -> _Store:
        history = _started()
        _run_phase(history, "research", "art-research")
        _start_phase(history, "plan")
        _fail(history, failed_phase_id="plan")
        return _Store(history)

    def test_a_started_phase_is_not_rerun_without_acknowledgement(self) -> None:
        store = self._failed_inside_plan()

        with pytest.raises(ValueError, match="phase plan started"):
            _resume(store)
        assert store.resumed() == []

    def test_acknowledged_the_resume_is_admitted_and_says_so(self) -> None:
        store = self._failed_inside_plan()
        _resume(store, acknowledge_external_effects=True)

        resumed = _resumed_event(store)
        assert resumed.resume_phase_id == "plan"
        assert resumed.external_effects_acknowledged is True

    def test_a_phase_that_never_started_needs_no_acknowledgement(self) -> None:
        store = _Store(_failed_between_phases())
        _resume(store)

        assert _resumed_event(store).external_effects_acknowledged is False

    def test_a_cancel_inside_a_phase_needs_both_decisions(self) -> None:
        history = _started()
        _run_phase(history, "research", "art-research")
        _start_phase(history, "plan")
        history.cancel_execution(CancelExecutionCommand(execution_id=PARENT, phase_id="plan"))
        store = _Store(history)

        with pytest.raises(ValueError, match="phase plan started"):
            _resume(store, override_cancellation=True)
        _resume(store, override_cancellation=True, acknowledge_external_effects=True)

        resumed = _resumed_event(store)
        assert resumed.cancellation_overridden is True
        assert resumed.external_effects_acknowledged is True


@pytest.mark.unit
class TestACompletedPhaseCannotBeReentered:
    """Codex review of #1453, finding 1.

    `start_phase` used to accept a phase that had already completed, and that
    door was the only way to reach either corruption:

    - a SECOND completion appends another attempt's artifacts to the same
      phase, mixing two attempts' output under one phase id;
    - a retry scheduled against it DROPS the artifacts of the attempt that did
      complete (`on_phase_retry_scheduled` pops them) while leaving the phase
      counted as completed.

    Both need the phase to be running again, and `retry_phase` demands exactly
    that while completion clears the running phase - so nothing else could get
    there. A resume is what made it expensive rather than merely untidy: it
    inherits the completed prefix, so an artifact-less "completed" phase hands
    the child work built on a predecessor whose output no longer exists
    (ADR-014 s7).
    """

    def test_starting_a_completed_phase_is_refused(self) -> None:
        history = _started()
        _run_phase(history, "research", "art-research")

        with pytest.raises(ValueError, match="already completed"):
            _start_phase(history, "research")

    def test_a_retry_cannot_discard_the_artifacts_of_a_completed_phase(self) -> None:
        """The reachable sequence the guard closes.

        Complete `research`, start it again, retry it: the retry pops the
        artifacts of the attempt that DID complete, while `research` stays in
        the completed set. The resume then inherits `research` with nothing in it
        and resumes at `plan`, handing the child work whose input is gone.
        """
        history = _started()
        _run_phase(history, "research", "art-research")

        with pytest.raises(ValueError, match="already completed"):
            _start_phase(history, "research")

        # The record is intact BECAUSE the re-entry was refused.
        _fail(history)
        store = _Store(history)
        _resume(store)
        assert _resumed_event(store).inherited_phases == [
            InheritedPhase(phase_id="research", artifact_ids=["art-research"])
        ]

    def test_a_second_completion_cannot_mix_two_attempts_artifacts(self) -> None:
        history = _started()
        _run_phase(history, "research", "art-first")

        with pytest.raises(ValueError, match="already completed"):
            _run_phase(history, "research", "art-second")

    def test_a_completed_phase_cannot_be_completed_again_while_another_runs(self) -> None:
        """Second review of #1453: `start_phase` was NOT the only door.

        No second `PhaseStarted` is needed. A stale or duplicated
        `CompletePhaseCommand` for a phase that already finished used to be
        admitted while a LATER phase was running, inflating the completed count
        and letting a second artifact land under the finished phase.
        """
        history = _started()
        _run_phase(history, "research", "art-research")
        _start_phase(history, "plan")

        with pytest.raises(ValueError, match="already completed"):
            _complete_phase(history, "research")

    def test_artifacts_cannot_be_collected_onto_a_completed_phase(self) -> None:
        """The third door, and the one a resume notices.

        A late `ArtifactsCollectedCommand` for a finished phase appended to that
        phase's artifact list, so the resume inherited an artifact the phase never
        produced during the attempt that completed it.
        """
        history = _started()
        _run_phase(history, "research", "art-research")
        _start_phase(history, "plan")

        with pytest.raises(ValueError, match="already completed"):
            _collect(history, "research", "art-injected")

    def test_the_in_phase_flow_is_untouched(self) -> None:
        """The guards must only close COMPLETED phases, not running ones.

        Collecting then completing the phase that is actually running is the
        normal path and stays admitted, for every phase in turn.
        """
        history = _started()
        for phase_id in PHASES:
            _start_phase(history, phase_id)
            _collect(history, phase_id, f"art-{phase_id}")
            _complete_phase(history, phase_id)

        assert history.status is ExecutionStatus.RUNNING
        assert history._completed_phases == len(PHASES)

    def test_a_stream_that_already_re_entered_a_completed_phase_still_loads(self) -> None:
        """The guard is on the COMMAND path, never on replay.

        Refusing during replay would be the worse bug: any production stream
        that already contains a second `PhaseStarted` for a completed phase
        would become unloadable, taking the execution with it. So the events
        are applied as recorded and only new commands are refused. This test
        builds that stream directly, because `start_phase` can no longer
        produce it.
        """
        history = _started()
        _run_phase(history, "research", "art-research")
        store = _Store(history)

        replayed_second_start = EventEnvelope(
            event=PhaseStartedEvent(
                workflow_id="wf-1",
                execution_id=PARENT,
                phase_id="research",
                phase_name="Research",
                phase_order=1,
                started_at=datetime.now(UTC),
                session_id=None,
            ),
            metadata=store._events[0].metadata,
        )
        store._events.append(replayed_second_start)

        reloaded = store.load()
        assert reloaded.status is ExecutionStatus.RUNNING
        # The re-entry was APPLIED, not skipped - otherwise this test would
        # pass without the stream ever containing the thing it is about.
        assert reloaded._phase_attempts["research"] == 2
        assert reloaded._running_phase_id == "research"
        # And the command that would have written it is still refused.
        with pytest.raises(ValueError, match="already completed"):
            _start_phase(reloaded, "research")

    def test_a_retry_before_completion_is_still_allowed(self) -> None:
        """The guard must not close the legitimate retry path.

        A phase being retried has NOT completed, so it is not in the completed
        set and its retry's `PhaseStarted` is admitted.
        """
        history = _started()
        _start_phase(history, "research")
        _collect(history, "research", "art-abandoned")
        history.retry_phase(
            RetryPhaseCommand(execution_id=PARENT, phase_id="research", reason="stream cut")
        )
        _run_phase(history, "research", "art-kept")

        _fail(history)
        store = _Store(history)
        _resume(store)
        assert _resumed_event(store).inherited_phases == [
            InheritedPhase(phase_id="research", artifact_ids=["art-kept"])
        ]


@pytest.mark.unit
class TestTheResumeGuardFailsClosed:
    """Codex review of #1453, finding 4.

    Under ADR-023 the store falls back to `GenericDomainEvent` when a stored
    event fails typed validation. The at-most-once rule therefore cannot be
    keyed on a FIELD of the resume event: `_evt` returns None for a field it
    cannot find, and the parent would replay with no evidence it had been
    resumed.
    """

    def test_a_resume_event_that_lost_its_child_id_still_refuses_a_second_resume(self) -> None:
        store = _Store(_failed_between_phases())
        _resume(store, "exec-resume-a")

        # The stored resume event as a stream that lost the field would replay it.
        stripped = WorkflowExecutionAggregate()
        stripped.rehydrate(
            [
                EventEnvelope(
                    event=_without_resume_id(e.event)
                    if isinstance(e.event, ExecutionResumedEvent)
                    else e.event,
                    metadata=e.metadata,
                )
                for e in store._events
            ]
        )

        assert stripped._resumed is True
        with pytest.raises(ValueError, match="has already been resumed"):
            stripped.resume_execution(
                ResumeExecutionCommand(execution_id=PARENT, resume_execution_id="exec-resume-b")
            )

    def test_the_refusal_names_what_it_can(self) -> None:
        """No child id to name, so the message says so rather than 'None'."""
        store = _Store(_failed_between_phases())
        _resume(store, "exec-resume-a")
        stripped = WorkflowExecutionAggregate()
        stripped.rehydrate(
            [
                EventEnvelope(
                    event=_without_resume_id(e.event)
                    if isinstance(e.event, ExecutionResumedEvent)
                    else e.event,
                    metadata=e.metadata,
                )
                for e in store._events
            ]
        )
        with pytest.raises(ValueError, match="does not name"):
            stripped.resume_execution(
                ResumeExecutionCommand(execution_id=PARENT, resume_execution_id="exec-resume-b")
            )
