"""EvidenceStepHandler on a resume takes over its parent's attempt (plan §A.7 3, PR 5c).

The parent posted step 1's dispatch and was interrupted. The child is started
from the parent's stored decision, and the handler runs against the child's
reloaded stream. What the forge double received is the evidence that nothing
was re-posted.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from syn_adapters.evidence.memory import (
    InMemoryEvidenceFiling,
    InMemoryEvidenceRunner,
    InMemoryRemoteBranchWriter,
    RunScript,
)
from syn_domain.contexts.orchestration._shared.evidence_contract import (
    EvidenceKind,
    EvidenceStepKind,
    StepOutcome,
)
from syn_domain.contexts.orchestration._shared.TodoValueObjects import TodoAction, TodoItem
from syn_domain.contexts.orchestration.domain.aggregate_execution.test_resume_evidence_gate import (
    CHILD,
    NOW,
    REPO,
    S,
    _child,
    _parent_inside_a_gate,
    _resume,
    _Stream,
)
from syn_domain.contexts.orchestration.ports.EvidenceRunnerPort import (
    Accepted,
    EvidenceAttemptRef,
    RunRef,
)
from syn_domain.contexts.orchestration.ports.RemoteBranchWriterPort import Removed
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

pytestmark = pytest.mark.unit

PARENT_RUN = RunRef(run_id=77, run_url="https://run/77")
#: Long after the parent's attempt: its deadline (NOW + 1h) has passed.
RESUMED_AT = NOW + timedelta(hours=6)
TIMINGS = EvidenceTimings()


def _integration_report(*, findable: bool = True) -> RunScript:
    report = _report(head=S).model_copy(update={"kind": EvidenceKind.INTEGRATION})
    return RunScript(Accepted(PARENT_RUN), found=PARENT_RUN if findable else None, report=report)


async def _forge_with_the_parents_run(script: RunScript) -> InMemoryEvidenceRunner:
    """The forge as the parent left it: its dispatch `d-1` was posted."""
    runner = InMemoryEvidenceRunner([script])
    await runner.dispatch(
        EvidenceAttemptRef(
            repository=REPO,
            kind=EvidenceStepKind.INTEGRATION,
            pr=42,
            head_sha=S,
            tests=("tests/test_x.py::test_kills",),
            dispatch_id="d-1",
            started_at=NOW,
        )
    )
    runner.dispatched.clear()
    return runner


async def _run_child_step(runner: InMemoryEvidenceRunner, *, adopted: bool) -> tuple[_Stream, str]:
    parent, gate_id = _parent_inside_a_gate(completed=True, adopted=adopted)
    _resume(parent)
    child, _started = _child(parent)
    now = RESUMED_AT

    async def sleep(seconds: float) -> None:
        nonlocal now
        now += timedelta(seconds=seconds)

    def clock() -> datetime:
        return now

    handler = EvidenceStepHandler(
        runner=runner,
        writer=InMemoryRemoteBranchWriter(Removed(S, "syn-app[bot]")),
        filing=InMemoryEvidenceFiling(),
        timings=TIMINGS,
        clock=clock,
        sleep=sleep,
    )

    async def save(aggregate: object) -> None:
        child.save(aggregate)  # type: ignore[arg-type]  # the handler saves the aggregate it was given

    todo = TodoItem(
        execution_id=CHILD,
        action=TodoAction.RUN_EVIDENCE_STEP,
        phase_id="implement",
        evidence_gate_id=gate_id,
        evidence_step=1,
    )
    await handler.handle(todo, child.load(), save, PhaseOutputCache())
    return child, gate_id


@pytest.mark.asyncio
async def test_the_parents_adopted_run_settles_the_step_with_no_dispatch() -> None:
    # Not findable by its nonce: only the run id the parent recorded can reach it.
    runner = await _forge_with_the_parents_run(_integration_report(findable=False))
    child, gate_id = await _run_child_step(runner, adopted=True)

    assert runner.dispatched == []
    gate = child.load().evidence_gate(gate_id)
    assert gate is not None
    assert gate.current is None
    assert gate.settled[1].outcome is StepOutcome.PASSED
    assert gate.attempts[1].dispatch_id == "d-1"
    assert gate.attempts[1].run_id == PARENT_RUN.run_id
    # A person-started resume is a new decision, with a new deadline.
    assert gate.attempts[1].not_after == RESUMED_AT + TIMINGS.step_deadline
    released = [type(e.event).__name__ for e in child.events][-1]
    assert released == "NextPhaseReadyEvent"


@pytest.mark.asyncio
async def test_a_dispatch_the_parent_never_saw_adopted_is_found_by_its_nonce() -> None:
    runner = await _forge_with_the_parents_run(_integration_report())
    child, gate_id = await _run_child_step(runner, adopted=False)

    assert runner.dispatched == []
    gate = child.load().evidence_gate(gate_id)
    assert gate is not None
    assert gate.settled[1].outcome is StepOutcome.PASSED
    assert gate.attempts[1].run_id == PARENT_RUN.run_id


@pytest.mark.asyncio
async def test_a_parent_dispatch_that_never_appeared_is_posted_once_afresh() -> None:
    lost = RunScript(Accepted(None), found=None)
    runner = await _forge_with_the_parents_run(lost)
    fresh = _integration_report()
    runner._scripts.append(  # pyright: ignore[reportPrivateUsage]  # queue the forge's answer to the fresh POST
        RunScript(Accepted(RunRef(run_id=78, run_url="https://run/78")), report=fresh.report)
    )
    child, gate_id = await _run_child_step(runner, adopted=False)

    (posted,) = runner.dispatched
    assert posted.dispatch_id != "d-1"
    gate = child.load().evidence_gate(gate_id)
    assert gate is not None
    assert gate.settled[1].outcome is StepOutcome.PASSED
    assert gate.attempts[1].attempt == 2
