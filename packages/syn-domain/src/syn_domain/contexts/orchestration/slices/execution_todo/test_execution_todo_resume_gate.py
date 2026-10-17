"""A resume that inherits an open evidence gate starts at the gate (plan §A.7 3, PR 5c).

Fed the child's REAL events, as stored: its `WorkflowExecutionStarted` built
from the parent's `ExecutionResumed`, then the settle and release its own
aggregate recorded.
"""

from __future__ import annotations

import json
from datetime import timedelta

import pytest

from syn_adapters.projection_stores.memory_store import InMemoryProjectionStore
from syn_domain.contexts.orchestration._shared.evidence_contract import StepOutcome
from syn_domain.contexts.orchestration.domain.aggregate_execution.commands import (
    SettleEvidenceStepCommand,
    StartEvidenceAttemptCommand,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.test_resume_evidence_gate import (
    CHILD,
    NOW,
    S,
    _child,
    _parent_inside_a_gate,
    _resume,
)
from syn_domain.contexts.orchestration.slices.execution_todo.projection import (
    ExecutionTodoProjection,
)
from syn_domain.contexts.orchestration.slices.execution_todo.value_objects import TodoAction

pytestmark = pytest.mark.unit


def _stored(event: object) -> dict[str, object]:
    return json.loads(event.model_dump_json())  # type: ignore[attr-defined]  # a DomainEvent


@pytest.mark.anyio
async def test_the_first_todo_is_the_first_unsettled_step_then_the_held_phase() -> None:
    parent, gate_id = _parent_inside_a_gate(completed=True)
    _resume(parent)
    child, (started,) = _child(parent)
    proj = ExecutionTodoProjection(store=InMemoryProjectionStore())

    await proj.on_workflow_execution_started(_stored(started))
    (first,) = await proj.get_pending(CHILD)
    assert (first.action, first.phase_id, first.evidence_gate_id, first.evidence_step) == (
        TodoAction.RUN_EVIDENCE_STEP,
        "implement",
        gate_id,
        1,
    )

    # Replaying the start changes nothing.
    await proj.on_workflow_execution_started(_stored(started))
    assert [t.evidence_step for t in await proj.get_pending(CHILD)] == [1]

    aggregate = child.load()
    aggregate.start_evidence_attempt(
        StartEvidenceAttemptCommand(CHILD, gate_id, 1, "d-1", NOW, NOW + timedelta(hours=1))
    )
    aggregate.settle_evidence_step(
        SettleEvidenceStepCommand(CHILD, gate_id, 1, StepOutcome.PASSED, head_sha_evidenced=S)
    )
    events = child.save(aggregate)
    settled, released = [e for e in events if type(e).__name__ != "EvidenceAttemptStartedEvent"]
    await proj.on_evidence_step_settled(settled)  # type: ignore[arg-type]  # the typed event, as the coordinator passes it
    await proj.on_next_phase_ready(_stored(released))

    (held,) = await proj.get_pending(CHILD)
    assert (held.action, held.phase_id) == (TodoAction.PROVISION_WORKSPACE, "review")
