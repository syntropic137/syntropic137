"""A resume of a cleanup gate carries on from where the parent's cleanup stood (plan §A.7, PR 5c).

The parent's certified review declared mutation and integration evidence in
front of the final phase, so its gate removes `.mutations/` and runs the
integration and the required check on the cleaned head S' (§A.3), holding
`finalize` and having skipped `fix`. The parent is interrupted at a point in
that cleanup, a person resumes it, and the child's handler runs the steps that
are left against the child's reloaded stream.
"""

from __future__ import annotations

import pytest

from syn_adapters.evidence.memory import (
    InMemoryEvidenceFiling,
    InMemoryEvidenceRunner,
    InMemoryRemoteBranchWriter,
    RunScript,
)
from syn_adapters.projection_stores.memory_store import InMemoryProjectionStore
from syn_domain.contexts.orchestration._shared.evidence_contract import (
    EvidenceKind,
    EvidenceStepKind,
    StepOutcome,
)
from syn_domain.contexts.orchestration._shared.TodoValueObjects import TodoAction, TodoItem
from syn_domain.contexts.orchestration.domain.aggregate_execution.commands import (
    InterruptExecutionCommand,
    SettleEvidenceStepCommand,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.start_pins import (
    phase_definitions_of,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.test_evidence_gate_aggregate import (
    EXECUTION,
    NOW,
    S_PRIME,
    S,
    _attempt,
    _collect,
    _declared,
    _gate_id,
    _send,
    _Store,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.test_resume_evidence_gate import (
    _pinned,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    ReviewVerdict,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
    CompletePhaseCommand,
    ResumeExecutionCommand,
    StartExecutionCommand,
    WorkflowExecutionAggregate,
)
from syn_domain.contexts.orchestration.domain.events.EvidenceStepSettledEvent import (
    EvidenceStepSettledEvent,
)
from syn_domain.contexts.orchestration.domain.events.WorkflowExecutionStartedEvent import (
    WorkflowExecutionStartedEvent,
)
from syn_domain.contexts.orchestration.ports.EvidenceRunnerPort import Accepted, RunRef
from syn_domain.contexts.orchestration.ports.RemoteBranchWriterPort import (
    Adopted,
    Removed,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.handlers.EvidenceStepHandler import (
    EvidenceStepHandler,
    EvidenceTimings,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.handlers.test_evidence_step_handler import (
    _report,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.processor_types import (
    PhaseOutputCache,
)
from syn_domain.contexts.orchestration.slices.execution_todo.projection import (
    ExecutionTodoProjection,
)
from syn_domain.contexts.orchestration.slices.execution_todo.test_execution_todo_resume_gate import (
    _stored,
)

pytestmark = pytest.mark.unit

CHILD = "exec-gate-cleanup-child"
BOT = "syn-app[bot]"
RUN = RunRef(run_id=9, run_url="https://run/9")
#: Plan of the parent's gate after `review` (§A.3): mutation on S, removal S -> S',
#: then the integration and the required check, both on S'.
MUTATION, REMOVAL, INTEGRATION, CHECK = range(4)


def _parent_in_cleanup() -> tuple[_Store, str]:
    """The parent's gate after `review`, its mutation step passed and nothing removed yet."""
    store = _started()
    _collect(store, "implement", policy=None)
    _complete(store, "implement")
    events = _collect(
        store,
        "review",
        declared=(_declared(), _declared(EvidenceKind.INTEGRATION)),
        verdict=ReviewVerdict.CERTIFIED,
    )
    gate_id = _gate_id(events)
    plan = [s.kind for s in store.load().evidence_gate(gate_id).plan]  # type: ignore[union-attr]  # just requested
    assert plan == [
        EvidenceStepKind.MUTATION,
        EvidenceStepKind.REMOVE_MUTATION_PATCHES,
        EvidenceStepKind.INTEGRATION,
        EvidenceStepKind.REQUIRED_CHECK,
    ]
    _send(store, _attempt(gate_id, MUTATION))
    _send(
        store,
        SettleEvidenceStepCommand(
            EXECUTION, gate_id, MUTATION, StepOutcome.PASSED, head_sha_evidenced=S
        ),
    )
    return store, gate_id


def _started() -> _Store:
    """The parent, started with its phases pinned so that a resume of it can start."""
    store = _Store()
    aggregate = WorkflowExecutionAggregate()
    phases = _pinned()
    aggregate.start_execution(
        StartExecutionCommand(
            execution_id=EXECUTION,
            workflow_id="wf",
            workflow_name="evidence",
            total_phases=len(phases),
            inputs={},
            phase_definitions=phase_definitions_of(phases),
            pinned_phases=phases,
        )
    )
    store.save(aggregate)
    return store


def _complete(store: _Store, phase_id: str) -> None:
    aggregate = store.load()
    aggregate.complete_phase(
        CompletePhaseCommand(
            execution_id=EXECUTION,
            workflow_id="wf",
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
    store.save(aggregate)


def _handler(
    runner: InMemoryEvidenceRunner, writer: InMemoryRemoteBranchWriter
) -> EvidenceStepHandler:
    return EvidenceStepHandler(
        runner=runner,
        writer=writer,
        filing=InMemoryEvidenceFiling(),
        timings=EvidenceTimings(),
        clock=lambda: NOW,
    )


async def _step(
    handler: EvidenceStepHandler, store: _Store, execution_id: str, gate_id: str, step: int
) -> None:
    async def save(aggregate: object) -> None:
        store.save(aggregate)  # type: ignore[arg-type]  # the handler saves the aggregate it was given

    todo = TodoItem(
        execution_id=execution_id,
        action=TodoAction.RUN_EVIDENCE_STEP,
        phase_id="review",
        evidence_gate_id=gate_id,
        evidence_step=step,
    )
    await handler.handle(todo, store.load(), save, PhaseOutputCache())


def _resumed(parent: _Store) -> tuple[_Store, WorkflowExecutionStartedEvent]:
    aggregate = parent.load()
    aggregate.interrupt_execution(
        InterruptExecutionCommand(execution_id=EXECUTION, phase_id="review")
    )
    parent.save(aggregate)
    aggregate = parent.load()
    aggregate.resume_execution(
        ResumeExecutionCommand(execution_id=EXECUTION, resume_execution_id=CHILD)
    )
    parent.save(aggregate)
    child = WorkflowExecutionAggregate()
    child.start_resume(parent.load().resume_start_command())
    store = _Store()
    (started,) = store.save(child)
    assert isinstance(started, WorkflowExecutionStartedEvent)
    return store, started


def _integration_runner() -> InMemoryEvidenceRunner:
    report = _report(head=S_PRIME).model_copy(update={"kind": EvidenceKind.INTEGRATION})
    return InMemoryEvidenceRunner([RunScript(Accepted(RUN), report=report)])


def _types(store: _Store) -> list[str]:
    return [type(e.event).__name__ for e in store.events]


@pytest.mark.asyncio
async def test_after_the_removal_the_child_runs_integration_on_s_prime() -> None:
    parent, gate_id = _parent_in_cleanup()
    await _step(
        _handler(InMemoryEvidenceRunner([]), InMemoryRemoteBranchWriter(Removed(S_PRIME, BOT))),
        parent,
        EXECUTION,
        gate_id,
        REMOVAL,
    )
    assert "MutationPatchesRemovedEvent" in _types(parent)
    child, _started = _resumed(parent)

    runner = _integration_runner()
    writer = InMemoryRemoteBranchWriter(Removed("f" * 40, BOT))
    handler = _handler(runner, writer)
    for step in (INTEGRATION, CHECK):
        await _step(handler, child, CHILD, gate_id, step)

    (posted,) = runner.dispatched
    assert (posted.kind, posted.head_sha) == (EvidenceStepKind.INTEGRATION, S_PRIME)
    assert writer.calls == []  # the removal is the parent's, inherited, never written again
    assert runner.checked == [("syntropic137/syntropic137", S_PRIME, "CI Success")]
    gate = child.load().evidence_gate(gate_id)
    assert gate is not None and gate.current is None
    manifest = gate.manifest()
    assert manifest.patch_removal is not None
    assert (manifest.patch_removal.after_sha, manifest.patch_removal.author) == (S_PRIME, BOT)
    assert [(s.index, s.outcome) for s in manifest.steps][:1] == [(MUTATION, StepOutcome.PASSED)]
    assert _types(child)[-1] == "NextPhaseReadyEvent"


@pytest.mark.asyncio
async def test_a_removal_whose_event_was_lost_is_adopted_not_written_again() -> None:
    # The parent's removal reached the branch; its event never did.
    parent, gate_id = _parent_in_cleanup()
    child, _started = _resumed(parent)
    assert child.load().evidence_gate(gate_id).current.index == REMOVAL  # type: ignore[union-attr]  # inherited open

    writer = InMemoryRemoteBranchWriter(Adopted(S_PRIME, BOT))
    await _step(_handler(InMemoryEvidenceRunner([]), writer), child, CHILD, gate_id, REMOVAL)

    # One compare-and-swap from S, answered by the commit already there.
    assert writer.calls == [("syntropic137/syntropic137", "feat/x", S, (".mutations",))]
    gate = child.load().evidence_gate(gate_id)
    assert gate is not None
    assert gate.removed is not None
    assert gate.removed.after_sha == S_PRIME
    assert gate.current is not None and gate.current.index == INTEGRATION
    assert gate.head_for(gate.current) == S_PRIME


@pytest.mark.anyio
async def test_the_held_skips_are_inherited_and_the_release_provisions_the_final_phase() -> None:
    parent, gate_id = _parent_in_cleanup()
    child, started = _resumed(parent)
    assert started.inherited_skipped_phase_ids == ["fix"]
    origin = started.resumed_from
    assert origin is not None and origin.inherited_evidence_gate is not None
    assert origin.inherited_evidence_gate.next_phase_id == "finalize"

    proj = ExecutionTodoProjection(store=InMemoryProjectionStore())
    await proj.on_workflow_execution_started(_stored(started))
    (first,) = await proj.get_pending(CHILD)
    assert (first.action, first.evidence_gate_id, first.evidence_step) == (
        TodoAction.RUN_EVIDENCE_STEP,
        gate_id,
        REMOVAL,
    )

    handler = _handler(_integration_runner(), InMemoryRemoteBranchWriter(Removed(S_PRIME, BOT)))
    for step in (REMOVAL, INTEGRATION, CHECK):
        await _step(handler, child, CHILD, gate_id, step)
    released = child.events[-1].event
    assert type(released).__name__ == "NextPhaseReadyEvent"
    assert released.next_phase_id == "finalize"  # pyright: ignore[reportAttributeAccessIssue]  # narrowed by name

    for envelope in child.events:
        if isinstance(envelope.event, EvidenceStepSettledEvent):
            await proj.on_evidence_step_settled(envelope.event)
    await proj.on_next_phase_ready(_stored(released))
    (held,) = await proj.get_pending(CHILD)
    assert (held.action, held.phase_id) == (TodoAction.PROVISION_WORKSPACE, "finalize")
    assert "fix" not in child.load()._completed_phase_ids  # pyright: ignore[reportPrivateUsage]  # never run
