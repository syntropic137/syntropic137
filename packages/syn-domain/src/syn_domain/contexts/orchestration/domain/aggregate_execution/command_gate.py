"""What a command Phase's recorded steps mean for the Execution (ADR-078 D5).

The handler records the steps' results; the aggregate decides, at collection,
whether the Execution goes on. Collection runs whatever the gate said, so a
failed build's logs are kept, and only then does a failed gate end the run.
That is the one place collection decides failure, and it lives here rather
than in the aggregate so it is testable as a pure function of the record.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from syn_domain.contexts.orchestration._shared.CommandStepValueObjects import (
    CommandStepOutcome,
    CommandStepResult,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.commands import (
    FailExecutionCommand,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    FailureClassification,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

#: `error_type` on the `WorkflowFailed` a failed gate writes.
COMMAND_GATE_ERROR_TYPE = "CommandPhaseFailed"


@dataclass(frozen=True)
class GateFailure:
    """Why a command Phase failed, in the words its `WorkflowFailed` will carry."""

    error: str
    classification: FailureClassification
    exit_code: int | None
    duration_seconds: float

    def command(
        self,
        *,
        execution_id: str,
        phase_id: str,
        completed_phases: int,
        total_phases: int,
        artifact_ids: Sequence[str],
    ) -> FailExecutionCommand:
        """The `FailExecutionCommand` this failure records, with the collected logs."""
        return FailExecutionCommand(
            execution_id=execution_id,
            error=self.error,
            error_type=COMMAND_GATE_ERROR_TYPE,
            failed_phase_id=phase_id,
            completed_phases=completed_phases,
            total_phases=total_phases,
            classification=self.classification,
            failed_phase_duration_seconds=self.duration_seconds,
            exit_code=self.exit_code,
            failed_phase_artifact_ids=tuple(artifact_ids),
        )


def judge_commands(
    phase_id: str, *, success: bool, timed_out: bool, steps: Sequence[CommandStepResult]
) -> GateFailure | None:
    """None when the gate passed; otherwise what stopped it.

    `gate` when the author's own step said no (a non-zero exit, a timeout,
    the Phase's deadline), `platform` when the platform could not run a step.
    A cancelled step never gets here: cancellation ends the run as cancelled.
    """
    if success:
        return None
    seconds = sum(step.duration_ms for step in steps) / 1000
    stopper = next((step for step in steps if step.stops_the_phase), None)
    if stopper is None:
        reason = "ran out of its deadline" if timed_out else "failed"
        return GateFailure(
            error=f"Command phase '{phase_id}' {reason}",
            classification=FailureClassification.GATE,
            exit_code=None,
            duration_seconds=seconds,
        )
    platform = stopper.outcome not in (CommandStepOutcome.FAILED, CommandStepOutcome.TIMED_OUT)
    said = {
        CommandStepOutcome.FAILED: f"exited {stopper.exit_code}",
        CommandStepOutcome.TIMED_OUT: "timed out",
        CommandStepOutcome.FAILED_TO_START: "could not be started",
        CommandStepOutcome.INTERRUPTED: "was interrupted",
    }.get(stopper.outcome, str(stopper.outcome))
    return GateFailure(
        error=f"Command phase '{phase_id}': step '{stopper.name}' {said}",
        classification=FailureClassification.PLATFORM if platform else FailureClassification.GATE,
        exit_code=stopper.exit_code,
        duration_seconds=seconds,
    )


@dataclass
class CommandGateRecord:
    """Each command Phase's latest recorded verdict, replayed from the stream.

    Overwritten per run of a phase, so a retried phase is judged by its last
    attempt only.
    """

    _failures: dict[str, GateFailure | None] = field(default_factory=dict)

    def report(
        self, phase_id: str, *, success: bool, timed_out: bool, steps: Sequence[object]
    ) -> None:
        """Record what a `PhaseCommandsCompleted` said; steps may be replayed dicts."""
        results = [
            step if isinstance(step, CommandStepResult) else CommandStepResult.model_validate(step)
            for step in steps
        ]
        self._failures[phase_id] = judge_commands(
            phase_id, success=success, timed_out=timed_out, steps=results
        )

    def failure_of(self, phase_id: str) -> GateFailure | None:
        """The failure recorded for this phase; None for a pass or an agent Phase."""
        return self._failures.get(phase_id)
