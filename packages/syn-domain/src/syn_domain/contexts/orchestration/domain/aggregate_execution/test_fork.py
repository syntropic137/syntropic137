"""The parent's decision to admit a fork (ADR-014 s7).

Every refusal here is asserted against a parent READ BACK FROM ITS STREAM,
not against the object that just handled a command. The rules are only worth
anything if they hold for the aggregate a later request loads - "already
forked" in particular is a fact that has to survive the process that recorded
it, or the one-fork rule is one fork per restart.
"""

from __future__ import annotations

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
    ForkExecutionCommand,
    InterruptExecutionCommand,
    PauseExecutionCommand,
    RetryPhaseCommand,
    StartExecutionCommand,
    StartPhaseCommand,
    WorkflowExecutionAggregate,
)
from syn_domain.contexts.orchestration.domain.events.ExecutionForkedEvent import (
    ExecutionForkedEvent,
)

if TYPE_CHECKING:
    from collections.abc import Callable

PARENT = "exec-parent"
FORK = "exec-fork"
PHASES = ("research", "plan", "implement")


# --- the parent's history ------------------------------------------------


def _started() -> WorkflowExecutionAggregate:
    aggregate = WorkflowExecutionAggregate()
    aggregate.start_execution(
        StartExecutionCommand(
            execution_id=PARENT,
            workflow_id="wf-1",
            workflow_name="Fork test",
            total_phases=len(PHASES),
            inputs={"task": "fork me"},
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


def _paused() -> WorkflowExecutionAggregate:
    aggregate = _started()
    _run_phase(aggregate, "research", "art-research-1")
    aggregate.pause_execution(PauseExecutionCommand(execution_id=PARENT, phase_id="plan"))
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

    def forked(self) -> list[ExecutionForkedEvent]:
        return [e.event for e in self._events if isinstance(e.event, ExecutionForkedEvent)]


def _fork(
    store: _Store,
    fork_id: str = FORK,
    *,
    override_cancellation: bool = False,
    acknowledge_external_effects: bool = False,
) -> None:
    """Load the parent, ask it for a fork, and save whatever it decided."""
    parent = store.load()
    parent.fork_execution(
        ForkExecutionCommand(
            execution_id=PARENT,
            fork_execution_id=fork_id,
            override_cancellation=override_cancellation,
            acknowledge_external_effects=acknowledge_external_effects,
        )
    )
    store.save(parent)


def _without_fork_id(event: ExecutionForkedEvent) -> GenericDomainEvent:
    """The stored fork event as a stream that lost `fork_execution_id` replays it.

    This is the ADR-023 fallback, built the way the store builds it: typed
    validation fails, so the event comes back as `GenericDomainEvent` carrying
    whatever fields the payload had. Dropping the one field is what makes the
    hazard real - a stand-in that still carried it would exercise nothing.
    """
    payload = event.model_dump()
    payload.pop("fork_execution_id", None)
    return GenericDomainEvent(event_type="ExecutionForked", **payload)


def _forked_event(store: _Store) -> ExecutionForkedEvent:
    forked = store.forked()
    assert len(forked) == 1, forked
    return forked[0]


# --- tests ------------------------------------------------------------------


@pytest.mark.unit
class TestForkedAtMostOnce:
    def test_a_second_fork_is_refused_by_the_reloaded_parent(self) -> None:
        """A retried request cannot fork the parent twice.

        Each attempt loads the parent from the store, as a separate request
        would, so the refusal comes from the stream and not from an object that
        remembers the first fork.

        What this does NOT prove: safety under two SIMULTANEOUS requests. This
        store appends without optimistic concurrency, so both would read a
        parent that had not yet been forked and both would pass this guard.
        Genuinely concurrent forks are refused one layer out, by the
        repository's expected-version check on append, and that belongs to the
        slice that wires one up - not to a fake store that cannot conflict.
        """
        store = _Store(_failed_between_phases())
        _fork(store, "exec-fork-a")

        with pytest.raises(ValueError, match="already been forked as exec-fork-a"):
            _fork(store, "exec-fork-b")
        assert [e.fork_execution_id for e in store.forked()] == ["exec-fork-a"]

    def test_the_parent_stays_the_terminal_run_it_was(self) -> None:
        store = _Store(_failed_between_phases())
        _fork(store)

        assert store.load().status is ExecutionStatus.FAILED


@pytest.mark.unit
class TestCancelledParent:
    def test_refused_without_the_override(self) -> None:
        store = _Store(_cancelled_between_phases())
        assert store.load().status is ExecutionStatus.CANCELLED

        with pytest.raises(
            ValueError,
            match="cancelled, and forking a cancelled execution needs an explicit override",
        ):
            _fork(store)
        assert store.forked() == []

    def test_refused_when_only_external_effects_are_acknowledged(self) -> None:
        """The two decisions are separate; one does not stand in for the other."""
        store = _Store(_cancelled_between_phases())

        with pytest.raises(ValueError, match="explicit override"):
            _fork(store, acknowledge_external_effects=True)
        assert store.forked() == []

    def test_accepted_with_the_override_and_says_so(self) -> None:
        store = _Store(_cancelled_between_phases())
        _fork(store, override_cancellation=True)

        forked = _forked_event(store)
        assert forked.fork_execution_id == FORK
        assert forked.cancellation_overridden is True

    def test_a_failed_parent_does_not_record_an_override_it_did_not_need(self) -> None:
        store = _Store(_failed_between_phases())
        _fork(store, override_cancellation=True)

        assert _forked_event(store).cancellation_overridden is False


@pytest.mark.unit
class TestForkableStatuses:
    @pytest.mark.parametrize(
        "history",
        [_failed_between_phases, _interrupted_between_phases],
        ids=["failed", "interrupted"],
    )
    def test_forkable_on_the_request_alone(
        self, history: Callable[[], WorkflowExecutionAggregate]
    ) -> None:
        store = _Store(history())
        _fork(store)

        forked = _forked_event(store)
        assert forked.execution_id == PARENT
        assert forked.fork_execution_id == FORK

    @pytest.mark.parametrize(
        ("history", "status"),
        [
            (_completed, ExecutionStatus.COMPLETED),
            (_running, ExecutionStatus.RUNNING),
            (_paused, ExecutionStatus.PAUSED),
        ],
        ids=["completed", "running", "paused"],
    )
    def test_never_forkable_even_with_both_flags(
        self, history: Callable[[], WorkflowExecutionAggregate], status: ExecutionStatus
    ) -> None:
        store = _Store(history())
        assert store.load().status is status

        with pytest.raises(ValueError, match=f"Cannot fork execution in status {status}"):
            _fork(store, override_cancellation=True, acknowledge_external_effects=True)
        assert store.forked() == []

    def test_an_execution_that_never_started_is_not_forkable(self) -> None:
        with pytest.raises(ValueError, match="has not been started"):
            WorkflowExecutionAggregate().fork_execution(
                ForkExecutionCommand(
                    execution_id=PARENT,
                    fork_execution_id=FORK,
                    override_cancellation=True,
                    acknowledge_external_effects=True,
                )
            )

    def test_a_fork_cannot_reuse_its_parents_id(self) -> None:
        store = _Store(_failed_between_phases())

        with pytest.raises(ValueError, match="execution id of its own"):
            _fork(store, PARENT)


@pytest.mark.unit
class TestInheritedPrefix:
    def test_completed_phases_are_inherited_with_every_collected_artifact(self) -> None:
        store = _Store(_failed_between_phases())
        _fork(store)

        forked = _forked_event(store)
        assert forked.inherited_phases == [
            InheritedPhase(phase_id="research", artifact_ids=["art-research-1", "art-research-2"])
        ]
        assert forked.resume_phase_id == "plan"

    def test_a_phase_completed_after_a_gap_is_not_inherited(self) -> None:
        """Only the CONTIGUOUS prefix: `implement` completed, `plan` did not.

        A rule that took every completed phase would inherit `implement` and
        resume at `plan`, handing the fork work built on a predecessor it is
        about to redo.
        """
        history = _started()
        _run_phase(history, "research", "art-research")
        _complete_phase(history, "implement")
        _fail(history)
        store = _Store(history)
        _fork(store)

        forked = _forked_event(store)
        assert [p.phase_id for p in forked.inherited_phases] == ["research"]
        assert forked.resume_phase_id == "plan"

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
        _fork(store)

        assert _forked_event(store).inherited_phases == [
            InheritedPhase(phase_id="research", artifact_ids=["art-kept"])
        ]

    def test_nothing_completed_inherits_nothing_and_resumes_at_the_first_phase(self) -> None:
        history = _started()
        _fail(history)
        store = _Store(history)
        _fork(store)

        forked = _forked_event(store)
        assert forked.inherited_phases == []
        assert forked.resume_phase_id == "research"

    def test_a_parent_with_no_unfinished_phase_is_refused(self) -> None:
        history = _started()
        for phase_id in PHASES:
            _run_phase(history, phase_id)
        _fail(history)
        store = _Store(history)

        with pytest.raises(ValueError, match="no unfinished phase"):
            _fork(store)


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
            _fork(store)
        assert store.forked() == []

    def test_acknowledged_the_fork_is_admitted_and_says_so(self) -> None:
        store = self._failed_inside_plan()
        _fork(store, acknowledge_external_effects=True)

        forked = _forked_event(store)
        assert forked.resume_phase_id == "plan"
        assert forked.external_effects_acknowledged is True

    def test_a_phase_that_never_started_needs_no_acknowledgement(self) -> None:
        store = _Store(_failed_between_phases())
        _fork(store)

        assert _forked_event(store).external_effects_acknowledged is False

    def test_a_cancel_inside_a_phase_needs_both_decisions(self) -> None:
        history = _started()
        _run_phase(history, "research", "art-research")
        _start_phase(history, "plan")
        history.cancel_execution(CancelExecutionCommand(execution_id=PARENT, phase_id="plan"))
        store = _Store(history)

        with pytest.raises(ValueError, match="phase plan started"):
            _fork(store, override_cancellation=True)
        _fork(store, override_cancellation=True, acknowledge_external_effects=True)

        forked = _forked_event(store)
        assert forked.cancellation_overridden is True
        assert forked.external_effects_acknowledged is True


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
    there. A fork is what made it expensive rather than merely untidy: it
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
        the completed set. The fork then inherits `research` with nothing in it
        and resumes at `plan`, handing the child work whose input is gone.
        """
        history = _started()
        _run_phase(history, "research", "art-research")

        with pytest.raises(ValueError, match="already completed"):
            _start_phase(history, "research")

        # The record is intact BECAUSE the re-entry was refused.
        _fail(history)
        store = _Store(history)
        _fork(store)
        assert _forked_event(store).inherited_phases == [
            InheritedPhase(phase_id="research", artifact_ids=["art-research"])
        ]

    def test_a_second_completion_cannot_mix_two_attempts_artifacts(self) -> None:
        history = _started()
        _run_phase(history, "research", "art-first")

        with pytest.raises(ValueError, match="already completed"):
            _run_phase(history, "research", "art-second")

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
        _fork(store)
        assert _forked_event(store).inherited_phases == [
            InheritedPhase(phase_id="research", artifact_ids=["art-kept"])
        ]


@pytest.mark.unit
class TestTheForkGuardFailsClosed:
    """Codex review of #1453, finding 4.

    Under ADR-023 the store falls back to `GenericDomainEvent` when a stored
    event fails typed validation. The at-most-once rule therefore cannot be
    keyed on a FIELD of the fork event: `_evt` returns None for a field it
    cannot find, and the parent would replay with no evidence it had been
    forked.
    """

    def test_a_fork_event_that_lost_its_child_id_still_refuses_a_second_fork(self) -> None:
        store = _Store(_failed_between_phases())
        _fork(store, "exec-fork-a")

        # The stored fork event as a stream that lost the field would replay it.
        stripped = WorkflowExecutionAggregate()
        stripped.rehydrate(
            [
                EventEnvelope(
                    event=_without_fork_id(e.event)
                    if isinstance(e.event, ExecutionForkedEvent)
                    else e.event,
                    metadata=e.metadata,
                )
                for e in store._events
            ]
        )

        assert stripped._forked is True
        with pytest.raises(ValueError, match="has already been forked"):
            stripped.fork_execution(
                ForkExecutionCommand(execution_id=PARENT, fork_execution_id="exec-fork-b")
            )

    def test_the_refusal_names_what_it_can(self) -> None:
        """No child id to name, so the message says so rather than 'None'."""
        store = _Store(_failed_between_phases())
        _fork(store, "exec-fork-a")
        stripped = WorkflowExecutionAggregate()
        stripped.rehydrate(
            [
                EventEnvelope(
                    event=_without_fork_id(e.event)
                    if isinstance(e.event, ExecutionForkedEvent)
                    else e.event,
                    metadata=e.metadata,
                )
                for e in store._events
            ]
        )
        with pytest.raises(ValueError, match="does not name"):
            stripped.fork_execution(
                ForkExecutionCommand(execution_id=PARENT, fork_execution_id="exec-fork-b")
            )
