"""A resume inherits its parent's open evidence gate (plan §A.7, PR 5c).

The parent stops inside a gate; a person resumes it. Every assertion is made
on aggregates read back through JSON, parent and child alike, because the
child's start is built from the parent's stored `ExecutionResumed` and the
child's gate from its own stored `WorkflowExecutionStarted`.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from event_sourcing import DomainEvent, EventEnvelope

from syn_domain.contexts.orchestration._shared.evidence_contract import (
    EvidenceKind,
    EvidenceRequest,
    StepOutcome,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.commands import (
    InterruptExecutionCommand,
    RecordEvidenceRunAdoptedCommand,
    SettleEvidenceStepCommand,
    StartEvidenceAttemptCommand,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.start_pins import (
    phase_definitions_of,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    AgentConfiguration,
    DeclaredEvidence,
    EvidenceGatePolicy,
    ExecutablePhase,
    ObservedHead,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
    AgentExecutionCompletedCommand,
    ArtifactsCollectedCommand,
    CompletePhaseCommand,
    ResumeExecutionCommand,
    StartExecutionCommand,
    StartPhaseCommand,
    WorkflowExecutionAggregate,
)
from syn_domain.contexts.orchestration.domain.events.ExecutionResumedEvent import (
    ExecutionResumedEvent,
)

pytestmark = pytest.mark.unit

PARENT = "exec-gate-parent"
CHILD = "exec-gate-child"
REPO = "syntropic137/syntropic137"
S = "a" * 40
NOW = datetime(2026, 10, 16, 20, 0, tzinfo=UTC)
PHASE_IDS = ("implement", "review", "fix", "finalize")


def _request(kind: EvidenceKind) -> DeclaredEvidence:
    return DeclaredEvidence(
        request=EvidenceRequest(
            kind=kind,
            repository=REPO,
            branch="feat/x",
            pr=42,
            head_sha=S,
            tests=("tests/test_x.py::test_kills",),
        )
    )


def _pinned() -> list[ExecutablePhase]:
    return [
        ExecutablePhase(
            phase_id=p,
            name=p,
            order=i + 1,
            agent_config=AgentConfiguration(model="sonnet"),
            prompt_template=p,
            timeout_seconds=600,
        )
        for i, p in enumerate(PHASE_IDS)
    ]


class _Stream:
    def __init__(self) -> None:
        self.events: list[EventEnvelope[DomainEvent]] = []

    def save(self, aggregate: WorkflowExecutionAggregate) -> list[DomainEvent]:
        new = [
            EventEnvelope(
                event=type(e.event).model_validate_json(e.event.model_dump_json()),
                metadata=e.metadata,
            )
            for e in aggregate.get_uncommitted_events()
        ]
        self.events.extend(new)
        aggregate.mark_events_as_committed()
        return [e.event for e in new]

    def load(self) -> WorkflowExecutionAggregate:
        fresh = WorkflowExecutionAggregate()
        fresh.rehydrate(list(self.events))
        return fresh


def _parent_inside_a_gate(*, completed: bool) -> tuple[_Stream, str]:
    """implement collected under a two-step gate; step 0 settled, step 1 dispatched and adopted.

    ``completed`` False is the window the plan does not name: the run stopped
    after the gate was requested and before `PhaseCompleted(implement)`.
    """
    stream = _Stream()
    parent = WorkflowExecutionAggregate()
    phases = _pinned()
    parent.start_execution(
        StartExecutionCommand(
            execution_id=PARENT,
            workflow_id="wf",
            workflow_name="evidence",
            total_phases=len(phases),
            inputs={},
            phase_definitions=phase_definitions_of(phases),
            pinned_phases=phases,
        )
    )
    parent.start_phase(
        StartPhaseCommand(
            execution_id=PARENT,
            workflow_id="wf",
            phase_id="implement",
            phase_name="implement",
            phase_order=1,
        )
    )
    parent.agent_execution_completed(
        AgentExecutionCompletedCommand(
            execution_id=PARENT,
            phase_id="implement",
            session_id="s",
            reported_evidence=(
                _request(EvidenceKind.MUTATION),
                _request(EvidenceKind.INTEGRATION),
            ),
        )
    )
    stream.save(parent)
    parent = stream.load()
    parent.artifacts_collected(
        ArtifactsCollectedCommand(
            execution_id=PARENT,
            phase_id="implement",
            artifact_ids=["art-implement"],
            observed_heads=[
                ObservedHead(
                    repository=REPO,
                    branch="feat/x",
                    readable=True,
                    head_sha=S,
                    mutation_patches_present=True,
                    open_pr_number=42,
                )
            ],
            evidence_gate=EvidenceGatePolicy(repositories=(REPO,)),
        )
    )
    (requested,) = [
        e for e in stream.save(parent) if type(e).__name__ == "EvidenceRequestedEvent"
    ]
    gate_id: str = requested.gate_id  # pyright: ignore[reportAttributeAccessIssue]  # narrowed by name above
    if completed:
        parent = stream.load()
        parent.complete_phase(
            CompletePhaseCommand(
                execution_id=PARENT,
                workflow_id="wf",
                phase_id="implement",
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
        stream.save(parent)
    parent = stream.load()
    parent.start_evidence_attempt(
        StartEvidenceAttemptCommand(PARENT, gate_id, 0, "d-0", NOW, NOW + timedelta(hours=1))
    )
    parent.settle_evidence_step(
        SettleEvidenceStepCommand(
            PARENT,
            gate_id,
            0,
            StepOutcome.PASSED,
            head_sha_evidenced=S,
            report_artifact_ids=["rep-0-json", "rep-0-md"],
        )
    )
    parent.start_evidence_attempt(
        StartEvidenceAttemptCommand(PARENT, gate_id, 1, "d-1", NOW, NOW + timedelta(hours=1))
    )
    parent.record_evidence_run_adopted(
        RecordEvidenceRunAdoptedCommand(PARENT, gate_id, 1, 1, 77, "https://run/77")
    )
    parent.interrupt_execution(InterruptExecutionCommand(execution_id=PARENT, phase_id="implement"))
    stream.save(parent)
    return stream, gate_id


def _resume(stream: _Stream) -> ExecutionResumedEvent:
    parent = stream.load()
    parent.resume_execution(ResumeExecutionCommand(execution_id=PARENT, resume_execution_id=CHILD))
    (resumed,) = stream.save(parent)
    assert isinstance(resumed, ExecutionResumedEvent)
    return resumed


def _child(parent: _Stream) -> tuple[_Stream, list[DomainEvent]]:
    child = WorkflowExecutionAggregate()
    child.start_resume(parent.load().resume_start_command())
    stream = _Stream()
    return stream, stream.save(child)


class TestTheParentAdmitsAGateResume:
    @pytest.mark.parametrize("completed", [True, False])
    def test_the_resume_point_is_the_held_phase_and_needs_no_acknowledgement(
        self, completed: bool
    ) -> None:
        stream, gate_id = _parent_inside_a_gate(completed=completed)
        resumed = _resume(stream)

        assert resumed.resume_phase_id == "review"
        assert resumed.external_effects_acknowledged is False
        assert [p.phase_id for p in resumed.inherited_phases] == ["implement"]
        gate = resumed.inherited_evidence_gate
        assert gate is not None
        assert gate.gate_id == gate_id
        assert gate.first_unsettled == 1
        assert [(s.index, s.outcome) for s in gate.settled] == [(0, StepOutcome.PASSED)]
        assert [(a.step, a.dispatch_id, a.run_id) for a in gate.attempts] == [(1, "d-1", 77)]

    def test_the_gated_phase_carries_its_settled_reports(self) -> None:
        stream, _gate_id = _parent_inside_a_gate(completed=True)
        (implement,) = _resume(stream).inherited_phases
        assert implement.artifact_ids == ["art-implement", "rep-0-json", "rep-0-md"]

    def test_a_resume_with_no_open_gate_carries_none(self) -> None:
        stream, gate_id = _parent_inside_a_gate(completed=True)
        parent = stream.load()
        # Reopen the run's history with the gate opened before the interruption.
        stream.events = [
            e for e in stream.events if type(e.event).__name__ != "WorkflowInterruptedEvent"
        ]
        parent = stream.load()
        parent.settle_evidence_step(
            SettleEvidenceStepCommand(PARENT, gate_id, 1, StepOutcome.FAILED, head_sha_evidenced=S)
        )
        parent.interrupt_execution(InterruptExecutionCommand(execution_id=PARENT, phase_id="review"))
        stream.save(parent)

        resumed = _resume(stream)
        assert resumed.inherited_evidence_gate is None
        assert "inherited_evidence_gate" not in resumed.model_dump()


class TestTheChildTakesTheGateOver:
    def test_the_child_start_carries_the_gate(self) -> None:
        parent, gate_id = _parent_inside_a_gate(completed=True)
        _resume(parent)
        _stream, (started,) = _child(parent)
        origin = started.resumed_from  # pyright: ignore[reportAttributeAccessIssue]
        assert origin.inherited_evidence_gate.gate_id == gate_id

    def test_the_childs_last_settle_releases_the_held_phase(self) -> None:
        parent, gate_id = _parent_inside_a_gate(completed=True)
        _resume(parent)
        child_stream, _started = _child(parent)
        child = child_stream.load()
        gate = child.evidence_gate(gate_id)
        assert gate is not None
        assert gate.current is not None and gate.current.index == 1
        assert gate.inherited_attempts[1].run_id == 77
        assert gate.attempts == {}

        child.start_evidence_attempt(
            StartEvidenceAttemptCommand(CHILD, gate_id, 1, "d-1", NOW, NOW + timedelta(hours=5))
        )
        child.settle_evidence_step(
            SettleEvidenceStepCommand(CHILD, gate_id, 1, StepOutcome.PASSED, head_sha_evidenced=S)
        )
        released = child_stream.save(child)
        assert [type(e).__name__ for e in released][-1] == "NextPhaseReadyEvent"
        assert released[-1].next_phase_id == "review"  # pyright: ignore[reportAttributeAccessIssue]
