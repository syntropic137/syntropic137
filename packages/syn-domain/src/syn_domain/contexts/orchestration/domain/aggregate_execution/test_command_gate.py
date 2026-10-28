"""A command Phase's recorded steps decide, at collection, whether the run goes on (ADR-078 D5).

Driven the way the processor drives it: record the steps, write the stream
through JSON into a FRESH aggregate (the restart D6 has to survive), then
collect. So the gate's verdict is never in process memory when the run is
failed or advanced.
"""

from __future__ import annotations

import pytest
from event_sourcing import DomainEvent, EventEnvelope

from syn_domain.contexts.orchestration._shared.command_phase import (
    CommandStepOutcome,
    CommandStepResult,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.command_gate import (
    COMMAND_GATE_ERROR_TYPE,
    judge_commands,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    FailureClassification,
    PhaseDefinition,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
    ArtifactsCollectedCommand,
    CancelExecutionCommand,
    RecordPhaseCommandsCommand,
    StartExecutionCommand,
    StartPhaseCommand,
    WorkflowExecutionAggregate,
)
from syn_domain.contexts.orchestration.domain.events.NextPhaseReadyEvent import (
    NextPhaseReadyEvent,
)
from syn_domain.contexts.orchestration.domain.events.PhaseCommandsCompletedEvent import (
    PhaseCommandsCompletedEvent,
)
from syn_domain.contexts.orchestration.domain.events.WorkflowFailedEvent import (
    WorkflowFailedEvent,
)

pytestmark = pytest.mark.unit

EXECUTION = "exec-gate"
PHASES = ("build", "review")
DEFINITIONS = [PhaseDefinition(phase_id=p, name=p, order=i + 1) for i, p in enumerate(PHASES)]


def _step(
    name: str,
    outcome: CommandStepOutcome,
    exit_code: int | None = None,
    *,
    allow_failure: bool = False,
) -> CommandStepResult:
    return CommandStepResult(
        name=name,
        outcome=outcome,
        exit_code=exit_code,
        duration_ms=1500,
        allow_failure=allow_failure,
    )


PASSED = _step("cargo-build", CommandStepOutcome.PASSED, 0)
FAILED = _step("wasm", CommandStepOutcome.FAILED, 2)
SKIPPED = _step("size", CommandStepOutcome.SKIPPED)


class _Store:
    """Append-only, and read back through JSON into a fresh aggregate."""

    def __init__(self) -> None:
        self.events: list[EventEnvelope[DomainEvent]] = []

    def save(self, aggregate: WorkflowExecutionAggregate) -> None:
        self.events.extend(
            EventEnvelope(
                event=type(e.event).model_validate_json(e.event.model_dump_json()),
                metadata=e.metadata,
            )
            for e in aggregate.get_uncommitted_events()
        )
        aggregate.mark_events_as_committed()

    def load(self) -> WorkflowExecutionAggregate:
        fresh = WorkflowExecutionAggregate()
        fresh.rehydrate(list(self.events))
        return fresh

    def of_type[E: DomainEvent](self, kind: type[E]) -> list[E]:
        return [e.event for e in self.events if isinstance(e.event, kind)]


def _collect_after(
    steps: list[CommandStepResult], *, success: bool, timed_out: bool = False
) -> _Store:
    """Run phase `build` as a command Phase, restart, and collect it."""
    store = _Store()
    aggregate = WorkflowExecutionAggregate()
    aggregate.start_execution(
        StartExecutionCommand(
            execution_id=EXECUTION,
            workflow_id="wf",
            workflow_name="gate",
            total_phases=len(PHASES),
            inputs={},
            phase_definitions=DEFINITIONS,
        )
    )
    aggregate.start_phase(
        StartPhaseCommand(
            execution_id=EXECUTION,
            workflow_id="wf",
            phase_id="build",
            phase_name="build",
            phase_order=1,
        )
    )
    aggregate.record_phase_commands(
        RecordPhaseCommandsCommand(
            execution_id=EXECUTION,
            phase_id="build",
            workspace_id="ws-1",
            success=success,
            timed_out=timed_out,
            steps=steps,
        )
    )
    store.save(aggregate)
    aggregate = store.load()  # a restart between the steps and collection
    aggregate.artifacts_collected(
        ArtifactsCollectedCommand(execution_id=EXECUTION, phase_id="build", artifact_ids=["a-1"])
    )
    store.save(aggregate)
    return store


class TestTheAggregateDecidesAtCollection:
    def test_a_passed_gate_selects_the_next_phase(self) -> None:
        store = _collect_after([PASSED], success=True)

        assert [e.next_phase_id for e in store.of_type(NextPhaseReadyEvent)] == ["review"]
        assert store.of_type(WorkflowFailedEvent) == []

    def test_a_failed_gate_fails_the_run_as_gate_and_runs_nothing_after_it(self) -> None:
        store = _collect_after([PASSED, FAILED, SKIPPED], success=False)

        assert store.of_type(NextPhaseReadyEvent) == []
        [failed] = store.of_type(WorkflowFailedEvent)
        assert failed.failure_classification is FailureClassification.GATE
        assert failed.failed_phase_id == "build"
        assert failed.error_type == COMMAND_GATE_ERROR_TYPE
        assert failed.error_message == "Command phase 'build': step 'wasm' exited 2"
        assert failed.exit_code == 2
        # The logs collected before the failure stay attached to it.
        assert failed.failed_phase_artifact_ids == ["a-1"]
        assert failed.failed_phase_duration_seconds == pytest.approx(4.5)

    def test_the_event_carries_no_session_and_every_step(self) -> None:
        store = _collect_after([PASSED, FAILED, SKIPPED], success=False)

        [recorded] = store.of_type(PhaseCommandsCompletedEvent)
        assert recorded.steps == [PASSED, FAILED, SKIPPED]
        assert recorded.workspace_id == "ws-1"
        assert "session_id" not in PhaseCommandsCompletedEvent.model_fields

    def test_a_step_that_could_not_start_is_the_platforms_failure(self) -> None:
        lost = _step("cargo-build", CommandStepOutcome.FAILED_TO_START)
        store = _collect_after([lost, SKIPPED], success=False)

        [failed] = store.of_type(WorkflowFailedEvent)
        assert failed.failure_classification is FailureClassification.PLATFORM
        assert failed.exit_code is None

    def test_recording_refuses_a_run_that_is_not_running(self) -> None:
        store = _collect_after([PASSED], success=True)
        aggregate = store.load()
        aggregate.cancel_execution(
            CancelExecutionCommand(execution_id=EXECUTION, phase_id="review")
        )

        with pytest.raises(ValueError, match="Cannot record phase commands"):
            aggregate.record_phase_commands(
                RecordPhaseCommandsCommand(
                    execution_id=EXECUTION,
                    phase_id="build",
                    workspace_id="ws-1",
                    success=True,
                    steps=[PASSED],
                )
            )


class TestJudgeCommands:
    def test_success_is_no_failure_even_with_an_excused_step(self) -> None:
        excused = _step("report", CommandStepOutcome.FAILED, 1, allow_failure=True)

        assert judge_commands("p", success=True, timed_out=False, steps=[excused]) is None

    def test_a_step_timeout_is_the_gate_saying_no(self) -> None:
        timed = _step("cargo-build", CommandStepOutcome.TIMED_OUT)

        failure = judge_commands("p", success=False, timed_out=False, steps=[timed])

        assert failure is not None
        assert failure.classification is FailureClassification.GATE
        assert failure.error == "Command phase 'p': step 'cargo-build' timed out"

    def test_the_phase_deadline_fails_the_gate_even_when_every_step_was_excused(self) -> None:
        # allow_failure excuses a step's own timeout, never the Phase's (D4).
        excused = _step("slow", CommandStepOutcome.TIMED_OUT, allow_failure=True)

        failure = judge_commands("p", success=False, timed_out=True, steps=[excused, SKIPPED])

        assert failure is not None
        assert failure.classification is FailureClassification.GATE
        assert failure.error == "Command phase 'p' ran out of its deadline"

    @pytest.mark.parametrize(
        ("outcome", "allow_failure", "stops"),
        [
            (CommandStepOutcome.PASSED, False, False),
            (CommandStepOutcome.SKIPPED, False, False),
            (CommandStepOutcome.FAILED, False, True),
            (CommandStepOutcome.FAILED, True, False),
            (CommandStepOutcome.TIMED_OUT, False, True),
            (CommandStepOutcome.TIMED_OUT, True, False),
            (CommandStepOutcome.FAILED_TO_START, True, True),
            (CommandStepOutcome.INTERRUPTED, True, True),
        ],
    )
    def test_which_outcomes_stop_the_phase(
        self, outcome: CommandStepOutcome, allow_failure: bool, stops: bool
    ) -> None:
        exit_code = 1 if outcome is CommandStepOutcome.FAILED else None
        step = _step("s", outcome, exit_code, allow_failure=allow_failure)

        assert step.stops_the_phase is stops
