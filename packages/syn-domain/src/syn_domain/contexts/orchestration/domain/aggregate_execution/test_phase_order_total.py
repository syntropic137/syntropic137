"""Phase order must be a TOTAL order wherever the aggregate sequences by it (#1455).

A start event whose phases share an order, or repeat a phase id, used to be
sorted by order alone and trusted. The consumers then decided by payload
order: a resume inherited a phase only because it happened to come first, and
`next_phase` skipped the tied phase without a word. These tests drive those
consumers off a REPLAYED stream - the start command now refuses such a
payload, so a stream is the only place one can still come from - in both
payload orders, so a pass cannot be an accident of which phase is listed first.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from event_sourcing import DomainEvent, EventEnvelope, EventMetadata, GenericDomainEvent

from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    FailureClassification,
    PhaseDefinition,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
    ArtifactsCollectedCommand,
    CompleteExecutionCommand,
    CompletePhaseCommand,
    FailExecutionCommand,
    ResumeExecutionCommand,
    StartExecutionCommand,
    StartPhaseCommand,
    WorkflowExecutionAggregate,
)
from syn_domain.contexts.orchestration.domain.events.ExecutionResumedEvent import (
    ExecutionResumedEvent,
)
from syn_domain.contexts.orchestration.domain.events.NextPhaseReadyEvent import (
    NextPhaseReadyEvent,
)

pytestmark = pytest.mark.unit

EXECUTION = "exec-tied"

#: B and A share order 1; C follows. Listed both ways round.
TIED_B_FIRST = [("B", 1), ("A", 1), ("C", 2)]
TIED_A_FIRST = [("A", 1), ("B", 1), ("C", 2)]
#: Two entries for one phase id, at distinct orders.
DUPLICATE_IDS = [("A", 1), ("A", 2), ("C", 3)]

NOT_A_TOTAL_ORDER = pytest.mark.parametrize(
    "phases",
    [TIED_B_FIRST, TIED_A_FIRST, DUPLICATE_IDS],
    ids=["tied-orders-B-first", "tied-orders-A-first", "duplicate-phase-ids"],
)


def _replayed(phases: list[tuple[str, int]]) -> WorkflowExecutionAggregate:
    """An execution read back from a start event that carries ``phases``."""
    started = GenericDomainEvent(
        event_type="WorkflowExecutionStarted",
        workflow_id="wf-1",
        execution_id=EXECUTION,
        workflow_name="Tied",
        started_at=datetime(2026, 10, 1, tzinfo=UTC).isoformat(),
        total_phases=len(phases),
        inputs={},
        phase_definitions=[
            {"phase_id": p, "name": p, "order": order, "timeout_seconds": 300}
            for p, order in phases
        ],
    )
    aggregate = WorkflowExecutionAggregate()
    aggregate.rehydrate(
        [
            EventEnvelope(
                event=started,
                metadata=EventMetadata(
                    aggregate_id=EXECUTION,
                    aggregate_type="WorkflowExecution",
                    event_type="WorkflowExecutionStarted",
                    version=1,
                    aggregate_nonce=1,
                    global_nonce=1,
                ),
            )
        ]
    )
    return aggregate


def _start_and_collect(aggregate: WorkflowExecutionAggregate, phase_id: str, order: int) -> None:
    aggregate.start_phase(
        StartPhaseCommand(
            execution_id=EXECUTION,
            workflow_id="wf-1",
            phase_id=phase_id,
            phase_name=phase_id,
            phase_order=order,
        )
    )
    aggregate.artifacts_collected(
        ArtifactsCollectedCommand(execution_id=EXECUTION, phase_id=phase_id, artifact_ids=[])
    )


def _complete(aggregate: WorkflowExecutionAggregate, phase_id: str) -> None:
    aggregate.complete_phase(
        CompletePhaseCommand(
            execution_id=EXECUTION,
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


def _emitted[E: DomainEvent](aggregate: WorkflowExecutionAggregate, kind: type[E]) -> list[E]:
    return [e.event for e in aggregate.get_uncommitted_events() if isinstance(e.event, kind)]


class TestAReplayedStartThatIsNotATotalOrderIsNotSequenced:
    @NOT_A_TOTAL_ORDER
    def test_completing_the_first_phase_names_no_next_phase(
        self, phases: list[tuple[str, int]]
    ) -> None:
        """Before #1455, B(1) completing made C next and skipped the tied A."""
        aggregate = _replayed(phases)
        first, order = phases[0]

        _start_and_collect(aggregate, first, order)

        assert _emitted(aggregate, NextPhaseReadyEvent) == []

    @NOT_A_TOTAL_ORDER
    def test_a_resume_inherits_nothing_it_would_have_chosen_by_payload_order(
        self, phases: list[tuple[str, int]]
    ) -> None:
        """Before #1455, B-first inherited B and A-first inherited nothing - same facts."""
        aggregate = _replayed(phases)
        first, order = phases[0]
        _start_and_collect(aggregate, first, order)
        _complete(aggregate, first)
        aggregate.fail_execution(
            FailExecutionCommand(
                execution_id=EXECUTION,
                error="boom",
                error_type="AgentError",
                failed_phase_id=None,
                completed_phases=1,
                total_phases=len(phases),
                classification=FailureClassification.UNCLASSIFIED,
            )
        )

        with pytest.raises(ValueError, match="no unfinished phase"):
            aggregate.resume_execution(
                ResumeExecutionCommand(
                    execution_id=EXECUTION,
                    resume_execution_id="exec-child",
                    acknowledge_external_effects=True,
                )
            )
        assert _emitted(aggregate, ExecutionResumedEvent) == []

    def test_a_total_order_is_still_sequenced(self) -> None:
        """The control: the same shape without the tie advances as it always did."""
        aggregate = _replayed([("A", 1), ("B", 2), ("C", 3)])

        _start_and_collect(aggregate, "A", 1)

        assert [e.next_phase_id for e in _emitted(aggregate, NextPhaseReadyEvent)] == ["B"]


class TestTheStartCommandRefusesToWriteOne:
    @NOT_A_TOTAL_ORDER
    def test_refused(self, phases: list[tuple[str, int]]) -> None:
        aggregate = WorkflowExecutionAggregate()

        with pytest.raises(ValueError, match="must be unique"):
            aggregate.start_execution(
                StartExecutionCommand(
                    execution_id=EXECUTION,
                    workflow_id="wf-1",
                    workflow_name="Tied",
                    total_phases=len(phases),
                    inputs={},
                    phase_definitions=[
                        PhaseDefinition(phase_id=p, name=p, order=order) for p, order in phases
                    ],
                )
            )
        assert aggregate.get_uncommitted_events() == []


def _complete_execution() -> CompleteExecutionCommand:
    return CompleteExecutionCommand(
        execution_id=EXECUTION,
        completed_phases=1,
        total_phases=3,
        total_input_tokens=0,
        total_output_tokens=0,
        total_cache_creation_tokens=0,
        total_cache_read_tokens=0,
        duration_seconds=1.0,
        artifact_ids=[],
    )


class TestAnUnorderedExecutionIsNeverCompletedAsSuccess:
    """No next phase is not "all done" when nothing was sequenced (#1455)."""

    @NOT_A_TOTAL_ORDER
    def test_completion_is_refused(self, phases: list[tuple[str, int]]) -> None:
        aggregate = _replayed(phases)

        with pytest.raises(ValueError, match="unordered"):
            aggregate.complete_execution(_complete_execution())

        assert aggregate.get_uncommitted_events() == []

    @NOT_A_TOTAL_ORDER
    def test_it_can_still_be_failed(self, phases: list[tuple[str, int]]) -> None:
        aggregate = _replayed(phases)

        aggregate.fail_execution(
            FailExecutionCommand(
                execution_id=EXECUTION,
                error="phase order is not a total order",
                error_type="InvalidPhaseOrder",
                failed_phase_id=None,
                completed_phases=0,
                total_phases=3,
                classification=FailureClassification.UNCLASSIFIED,
            )
        )

        assert aggregate.status.value == "failed"

    def test_a_total_order_still_completes(self) -> None:
        aggregate = _replayed([("A", 1), ("B", 2), ("C", 3)])

        aggregate.complete_execution(_complete_execution())

        assert aggregate.status.value == "completed"

    def test_a_start_without_phase_definitions_still_completes(self) -> None:
        """The legacy "does not sequence" case is not a conflict."""
        aggregate = _replayed([])

        aggregate.complete_execution(_complete_execution())

        assert aggregate.status.value == "completed"
