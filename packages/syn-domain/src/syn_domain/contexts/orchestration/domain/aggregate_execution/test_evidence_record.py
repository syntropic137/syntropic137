"""Declared evidence and observed heads survive command -> event -> replay (plan §A.2, PR 5a).

Every assertion is made on a FRESH aggregate rebuilt from events written
through JSON, so a field the event builder drops, or a handler that does not
apply, fails here even though the command was built correctly.
"""

from __future__ import annotations

import pytest
from event_sourcing import DomainEvent, EventEnvelope

from syn_domain.contexts.orchestration._shared.evidence_contract import (
    EvidenceKind,
    EvidenceRequest,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.evidence_record import (
    DeclaredEvidence,
    ObservedHead,
    read_declared_evidence,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    PhaseDefinition,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
    AgentExecutionCompletedCommand,
    ArtifactsCollectedCommand,
    StartExecutionCommand,
    StartPhaseCommand,
    WorkflowExecutionAggregate,
)
from syn_domain.contexts.orchestration.domain.events.AgentExecutionCompletedEvent import (
    AgentExecutionCompletedEvent,
)

pytestmark = pytest.mark.unit

EXECUTION = "exec-evidence"
SHA = "a" * 40
REQUEST = EvidenceRequest(
    kind=EvidenceKind.MUTATION,
    repository="syntropic137/syntropic137",
    branch="feat/x",
    pr=42,
    head_sha=SHA,
    tests=("tests/test_x.py::test_kills",),
)
DECLARED = (DeclaredEvidence(request=REQUEST), DeclaredEvidence.refused("kind: bad"))
HEAD = ObservedHead(
    repository="syntropic137/syntropic137",
    branch="feat/x",
    readable=True,
    head_sha=SHA,
    mutation_patches_present=True,
    open_pr_number=42,
)


class _Store:
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


def _running(store: _Store) -> WorkflowExecutionAggregate:
    aggregate = WorkflowExecutionAggregate()
    aggregate.start_execution(
        StartExecutionCommand(
            execution_id=EXECUTION,
            workflow_id="wf",
            workflow_name="evidence",
            total_phases=1,
            inputs={},
            phase_definitions=[PhaseDefinition(phase_id="implement", name="implement", order=1)],
        )
    )
    aggregate.start_phase(
        StartPhaseCommand(
            execution_id=EXECUTION,
            workflow_id="wf",
            phase_id="implement",
            phase_name="implement",
            phase_order=1,
        )
    )
    store.save(aggregate)
    return aggregate


def _agent_finished(
    aggregate: WorkflowExecutionAggregate, declared: tuple[DeclaredEvidence, ...]
) -> None:
    aggregate.agent_execution_completed(
        AgentExecutionCompletedCommand(
            execution_id=EXECUTION,
            phase_id="implement",
            session_id="s",
            reported_evidence=declared,
        )
    )


def test_declared_evidence_is_replayed_from_the_event_stream() -> None:
    store = _Store()
    aggregate = _running(store)
    _agent_finished(aggregate, DECLARED)
    store.save(aggregate)

    assert store.load().declared_evidence_for("implement") == DECLARED


def test_a_retry_that_declares_nothing_does_not_inherit_the_abandoned_attempt() -> None:
    store = _Store()
    aggregate = _running(store)
    _agent_finished(aggregate, DECLARED)
    _agent_finished(aggregate, ())
    store.save(aggregate)

    assert store.load().declared_evidence_for("implement") == ()


def test_observed_heads_are_replayed_from_the_event_stream() -> None:
    store = _Store()
    aggregate = _running(store)
    _agent_finished(aggregate, ())
    aggregate.artifacts_collected(
        ArtifactsCollectedCommand(
            execution_id=EXECUTION, phase_id="implement", artifact_ids=[], observed_heads=[HEAD]
        )
    )
    store.save(aggregate)

    assert store.load().observed_heads_for("implement") == (HEAD,)


def test_heads_attached_after_the_command_is_built_still_reach_the_event() -> None:
    """`observed` is how collection attaches them; the event must carry those."""
    store = _Store()
    aggregate = _running(store)
    _agent_finished(aggregate, ())
    command = ArtifactsCollectedCommand(
        execution_id=EXECUTION, phase_id="implement", artifact_ids=[]
    )
    command.observed([HEAD])
    aggregate.artifacts_collected(command)
    store.save(aggregate)

    assert store.load().observed_heads_for("implement") == (HEAD,)


def test_an_event_written_before_evidence_existed_replays_as_nothing_declared() -> None:
    legacy = AgentExecutionCompletedEvent.model_validate(
        {
            "workflow_id": "wf",
            "execution_id": EXECUTION,
            "phase_id": "implement",
            "session_id": "s",
            "completed_at": "2026-10-01T00:00:00Z",
            "exit_code": 0,
            "input_tokens": 0,
            "output_tokens": 0,
        }
    )
    assert legacy.reported_evidence == []


def test_an_unreadable_stored_declaration_replays_as_unreadable_not_as_nothing() -> None:
    replayed = read_declared_evidence([{"request": None, "unreadable": None}])

    assert len(replayed) == 1
    assert replayed[0].request is None
    assert replayed[0].unreadable


def test_a_declaration_is_a_request_or_unreadable_never_both() -> None:
    with pytest.raises(ValueError, match="either a request or unreadable"):
        DeclaredEvidence(request=REQUEST, unreadable="also this")
    with pytest.raises(ValueError, match="either a request or unreadable"):
        DeclaredEvidence()
