"""The aggregate holds a transition for evidence and releases it (plan §A.3-§A.5, PR 5b).

Driven the way the processor drives it, with the stream written through JSON
and loaded into a FRESH aggregate between commands, so every decision below is
one a restart rebuilds from the stream - never one held in process memory.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from event_sourcing import DomainEvent, EventEnvelope

from syn_domain.contexts.orchestration._shared.evidence_contract import (
    EvidenceKind,
    EvidenceRequest,
    EvidenceStepKind,
    StepOutcome,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.commands import (
    RecordEvidenceRunAdoptedCommand,
    RecordMutationPatchesRemovedCommand,
    SettleEvidenceStepCommand,
    StartEvidenceAttemptCommand,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.evidence_gate import (
    MUTATION_NOT_PASSED,
    PATCHES_NOT_REMOVED,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    DeclaredEvidence,
    EvidenceGatePolicy,
    ObservedHead,
    PhaseDefinition,
    ReviewVerdict,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
    AgentExecutionCompletedCommand,
    ArtifactsCollectedCommand,
    StartExecutionCommand,
    StartPhaseCommand,
    WorkflowExecutionAggregate,
)

pytestmark = pytest.mark.unit

EXECUTION = "exec-gate"
REPO = "syntropic137/syntropic137"
S = "a" * 40
S_PRIME = "c" * 40
POLICY = EvidenceGatePolicy(repositories=(REPO,))
PHASES = [
    PhaseDefinition(phase_id="implement", name="implement", order=1),
    PhaseDefinition(phase_id="review", name="review", order=2),
    PhaseDefinition(phase_id="fix", name="fix", order=3),
    PhaseDefinition(phase_id="finalize", name="finalize", order=4),
]
NOW = datetime(2026, 10, 16, 20, 0, tzinfo=UTC)


def _declared(kind: EvidenceKind = EvidenceKind.MUTATION) -> DeclaredEvidence:
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


HEAD = ObservedHead(
    repository=REPO,
    branch="feat/x",
    readable=True,
    head_sha=S,
    mutation_patches_present=True,
    open_pr_number=42,
)


class _Store:
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


def _types(events: list[DomainEvent]) -> list[str]:
    return [type(e).__name__ for e in events]


def _collect(
    store: _Store,
    phase_id: str,
    *,
    declared: tuple[DeclaredEvidence, ...] = (),
    verdict: ReviewVerdict | None = None,
    policy: EvidenceGatePolicy | None = POLICY,
    head: ObservedHead = HEAD,
) -> list[DomainEvent]:
    """Run ``phase_id`` from start to collection, one save per to-do item."""
    aggregate = store.load()
    aggregate.start_phase(
        StartPhaseCommand(
            execution_id=EXECUTION,
            workflow_id="wf",
            phase_id=phase_id,
            phase_name=phase_id,
            phase_order=next(p.order for p in PHASES if p.phase_id == phase_id),
        )
    )
    aggregate.agent_execution_completed(
        AgentExecutionCompletedCommand(
            execution_id=EXECUTION,
            phase_id=phase_id,
            session_id="s",
            reported_evidence=declared,
            reported_review_verdict=verdict,
        )
    )
    store.save(aggregate)
    aggregate = store.load()
    aggregate.artifacts_collected(
        ArtifactsCollectedCommand(
            execution_id=EXECUTION,
            phase_id=phase_id,
            artifact_ids=[],
            observed_heads=[head],
            evidence_gate=policy,
        )
    )
    return store.save(aggregate)


def _started() -> _Store:
    store = _Store()
    aggregate = WorkflowExecutionAggregate()
    aggregate.start_execution(
        StartExecutionCommand(
            execution_id=EXECUTION,
            workflow_id="wf",
            workflow_name="evidence",
            total_phases=len(PHASES),
            inputs={},
            phase_definitions=PHASES,
        )
    )
    store.save(aggregate)
    return store


def _gate_id(events: list[DomainEvent]) -> str:
    (requested,) = [e for e in events if type(e).__name__ == "EvidenceRequestedEvent"]
    gate_id: str = requested.gate_id  # pyright: ignore[reportAttributeAccessIssue]  # narrowed by name above
    return gate_id


def _send(store: _Store, command: object) -> list[DomainEvent]:
    aggregate = store.load()
    handlers = {
        StartEvidenceAttemptCommand: aggregate.start_evidence_attempt,
        RecordEvidenceRunAdoptedCommand: aggregate.record_evidence_run_adopted,
        RecordMutationPatchesRemovedCommand: aggregate.record_mutation_patches_removed,
        SettleEvidenceStepCommand: aggregate.settle_evidence_step,
    }
    handlers[type(command)](command)  # pyright: ignore[reportArgumentType]  # keyed by the command's own type
    return store.save(aggregate)


def _attempt(
    gate_id: str, step: int, dispatch_id: str = "d-1", not_after: datetime = NOW
) -> StartEvidenceAttemptCommand:
    return StartEvidenceAttemptCommand(
        execution_id=EXECUTION,
        gate_id=gate_id,
        step=step,
        dispatch_id=dispatch_id,
        started_at=NOW,
        not_after=not_after,
    )


def _settle(
    gate_id: str, step: int, outcome: StepOutcome = StepOutcome.PASSED, reason: str | None = None
) -> SettleEvidenceStepCommand:
    return SettleEvidenceStepCommand(
        execution_id=EXECUTION,
        gate_id=gate_id,
        step=step,
        outcome=outcome,
        reason=reason,
        head_sha_evidenced=S,
    )


class TestTheFlag:
    def test_without_a_policy_a_declaration_advances_as_today(self) -> None:
        store = _started()
        events = _collect(store, "implement", declared=(_declared(),), policy=None)
        assert "EvidenceRequestedEvent" not in _types(events)
        assert "NextPhaseReadyEvent" in _types(events)

    def test_with_a_policy_the_transition_is_held(self) -> None:
        store = _started()
        events = _collect(store, "implement", declared=(_declared(),))
        assert "EvidenceRequestedEvent" in _types(events)
        assert "NextPhaseReadyEvent" not in _types(events)


class TestAttemptProtocol:
    def test_attempt_adopt_settle_releases_the_held_phase(self) -> None:
        store = _started()
        gate_id = _gate_id(_collect(store, "implement", declared=(_declared(),)))

        _send(store, _attempt(gate_id, 0))
        attempt = store.load().evidence_gate(gate_id)
        assert attempt is not None
        assert attempt.attempts[0].dispatch_id == "d-1"

        _send(
            store, RecordEvidenceRunAdoptedCommand(EXECUTION, gate_id, 0, 1, 99, "https://run/99")
        )
        released = _send(store, _settle(gate_id, 0))

        assert _types(released) == ["EvidenceStepSettledEvent", "NextPhaseReadyEvent"]
        ready = released[1]
        assert ready.next_phase_id == "review"  # pyright: ignore[reportAttributeAccessIssue]
        assert ready.completed_phase_id == "implement"  # pyright: ignore[reportAttributeAccessIssue]
        gate = store.load().evidence_gate(gate_id)
        assert gate is not None
        assert gate.attempts[0].run_id == 99
        assert gate.current is None

    def test_a_retry_shares_the_first_attempts_deadline(self) -> None:
        store = _started()
        gate_id = _gate_id(_collect(store, "implement", declared=(_declared(),)))
        _send(store, _attempt(gate_id, 0, "d-1", NOW + timedelta(hours=1)))
        (second,) = _send(store, _attempt(gate_id, 0, "d-2", NOW + timedelta(hours=9)))
        assert second.attempt == 2  # pyright: ignore[reportAttributeAccessIssue]
        assert second.not_after == NOW + timedelta(hours=1)  # pyright: ignore[reportAttributeAccessIssue]

    def test_a_third_attempt_is_refused(self) -> None:
        store = _started()
        gate_id = _gate_id(_collect(store, "implement", declared=(_declared(),)))
        _send(store, _attempt(gate_id, 0, "d-1"))
        _send(store, _attempt(gate_id, 0, "d-2"))
        with pytest.raises(ValueError, match="used its 2 attempts"):
            _send(store, _attempt(gate_id, 0, "d-3"))

    def test_adopting_for_an_attempt_that_is_not_current_is_refused(self) -> None:
        store = _started()
        gate_id = _gate_id(_collect(store, "implement", declared=(_declared(),)))
        _send(store, _attempt(gate_id, 0, "d-1"))
        _send(store, _attempt(gate_id, 0, "d-2"))
        with pytest.raises(ValueError, match="not the current attempt"):
            _send(store, RecordEvidenceRunAdoptedCommand(EXECUTION, gate_id, 0, 1, 5, "u"))

    def test_adopting_twice_is_refused(self) -> None:
        store = _started()
        gate_id = _gate_id(_collect(store, "implement", declared=(_declared(),)))
        _send(store, _attempt(gate_id, 0))
        _send(store, RecordEvidenceRunAdoptedCommand(EXECUTION, gate_id, 0, 1, 5, "u"))
        with pytest.raises(ValueError, match="already adopted"):
            _send(store, RecordEvidenceRunAdoptedCommand(EXECUTION, gate_id, 0, 1, 6, "u"))

    def test_settling_twice_is_refused(self) -> None:
        store = _started()
        gate_id = _gate_id(
            _collect(
                store, "implement", declared=(_declared(), _declared(EvidenceKind.INTEGRATION))
            )
        )
        _send(store, _settle(gate_id, 0))
        with pytest.raises(ValueError, match="not its current step"):
            _send(store, _settle(gate_id, 0))

    def test_an_attempt_on_a_settled_step_is_refused(self) -> None:
        store = _started()
        gate_id = _gate_id(
            _collect(
                store, "implement", declared=(_declared(), _declared(EvidenceKind.INTEGRATION))
            )
        )
        _send(store, _settle(gate_id, 0))
        with pytest.raises(ValueError, match="not its current step"):
            _send(store, _attempt(gate_id, 0))

    def test_void_without_a_reason_is_refused(self) -> None:
        store = _started()
        gate_id = _gate_id(_collect(store, "implement", declared=(_declared(),)))
        with pytest.raises(ValueError, match="must say why"):
            _send(store, _settle(gate_id, 0, StepOutcome.VOID))

    def test_a_predetermined_step_settles_only_as_decided(self) -> None:
        store = _started()
        refused = DeclaredEvidence.refused("kind: bad")
        clean = HEAD.model_copy(update={"mutation_patches_present": False})
        gate_id = _gate_id(_collect(store, "implement", declared=(refused,), head=clean))
        with pytest.raises(ValueError, match="was decided as void"):
            _send(store, _settle(gate_id, 0))
        with pytest.raises(ValueError, match="dispatches nothing"):
            _send(store, _attempt(gate_id, 0))
        released = _send(
            store,
            _settle(gate_id, 0, StepOutcome.VOID, "unreadable evidence request: kind: bad"),
        )
        assert "NextPhaseReadyEvent" in _types(released)


class TestCleanupBeforeTheFinalPhase:
    def _gate(self) -> tuple[_Store, str]:
        store = _started()
        _collect(store, "implement", policy=None)
        events = _collect(
            store,
            "review",
            declared=(_declared(), _declared(EvidenceKind.INTEGRATION)),
            verdict=ReviewVerdict.CERTIFIED,
        )
        return store, _gate_id(events)

    def test_the_plan_cleans_up_and_the_skips_are_decided_at_request(self) -> None:
        store, gate_id = self._gate()
        gate = store.load().evidence_gate(gate_id)
        assert gate is not None
        assert [s.kind for s in gate.plan] == [
            EvidenceStepKind.MUTATION,
            EvidenceStepKind.REMOVE_MUTATION_PATCHES,
            EvidenceStepKind.INTEGRATION,
            EvidenceStepKind.REQUIRED_CHECK,
        ]
        assert (gate.next_phase_id, gate.skipped_phase_ids) == ("finalize", ("fix",))

    def test_removal_waits_for_mutation_then_moves_later_steps_to_s_prime(self) -> None:
        store, gate_id = self._gate()
        _send(store, _settle(gate_id, 0))
        removed = _send(
            store,
            RecordMutationPatchesRemovedCommand(EXECUTION, gate_id, 1, S_PRIME, "syn-app[bot]"),
        )
        assert _types(removed) == ["MutationPatchesRemovedEvent", "EvidenceStepSettledEvent"]
        gate = store.load().evidence_gate(gate_id)
        assert gate is not None
        assert gate.head_for(gate.plan[2]) == S_PRIME
        _send(store, _settle(gate_id, 2))
        released = _send(store, _settle(gate_id, 3))
        assert released[-1].next_phase_id == "finalize"  # pyright: ignore[reportAttributeAccessIssue]
        assert released[-1].skipped_phase_ids == ["fix"]  # pyright: ignore[reportAttributeAccessIssue]
        manifest = store.load().evidence_gate(gate_id)
        assert manifest is not None
        assert manifest.manifest().patch_removal is not None

    def test_a_failed_mutation_blocks_removal_and_the_required_check(self) -> None:
        store, gate_id = self._gate()
        _send(store, _settle(gate_id, 0, StepOutcome.FAILED))
        with pytest.raises(ValueError, match="not allowed"):
            _send(store, RecordMutationPatchesRemovedCommand(EXECUTION, gate_id, 1, S_PRIME, "bot"))
        _send(store, _settle(gate_id, 1, StepOutcome.VOID, MUTATION_NOT_PASSED))
        gate = store.load().evidence_gate(gate_id)
        assert gate is not None
        assert gate.head_for(gate.plan[2]) == S
        _send(store, _settle(gate_id, 2))
        with pytest.raises(ValueError, match="was decided as void"):
            _send(store, _settle(gate_id, 3))
        released = _send(store, _settle(gate_id, 3, StepOutcome.VOID, PATCHES_NOT_REMOVED))
        assert "NextPhaseReadyEvent" in _types(released)

    def test_a_removal_cannot_be_settled_passed_without_recording_it(self) -> None:
        store, gate_id = self._gate()
        _send(store, _settle(gate_id, 0))
        with pytest.raises(ValueError, match="only by recording"):
            _send(store, _settle(gate_id, 1))
