"""Regression test for #1044: two executions of one workflow definition share
a processor instance and, before the fix, shared `_phase_started_at` /
`_phase_session_ids` keyed by bare `phase_id`.

Drives the REAL write path (`_handle_provision`, `_handle_run_agent`) for two
executions of the same phase id on one shared `WorkflowExecutionProcessor`,
then drives the REAL read/teardown path (`_fail_execution`) for one of them.
Asserting only on the dict that was retyped would not catch a regression to
the bare key: the fixture values below are session ids that could only end up
attributed correctly if both the write sites (tuple key at insert) and the
read site (`failed_phase_outcome`) agree on `(execution_id, phase_id)`.
"""

from __future__ import annotations

import pytest

from syn_domain.contexts.orchestration._shared.TodoValueObjects import TodoAction, TodoItem
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    AgentConfiguration,
    ExecutablePhase,
    PhaseDefinition,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
    StartExecutionCommand,
    WorkflowExecutionAggregate,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.processor_types import (
    PhaseOutputCache,
)
from syn_domain.testing.fake_agent_handler import FakeAgentExecutionHandler

from .test_processor_smoke import _make_processor

pytestmark = pytest.mark.unit

#: Same phase_id used by both executions -- the collision surface the issue
#: describes. A workflow definition's phase ids are unique WITHIN it, not
#: across concurrently running executions of it.
PHASE_ID = "implement"


def _phase() -> ExecutablePhase:
    return ExecutablePhase(
        phase_id=PHASE_ID,
        name="Implement",
        order=1,
        description="single phase",
        agent_config=AgentConfiguration(),
        prompt_template="do the thing",
        output_artifact_type="text",
        timeout_seconds=30,
    )


def _started_aggregate(execution_id: str) -> WorkflowExecutionAggregate:
    agg = WorkflowExecutionAggregate()
    agg.start_execution(
        StartExecutionCommand(
            execution_id=execution_id,
            workflow_id="wf-shared",
            workflow_name="Shared Workflow",
            total_phases=1,
            inputs={},
            phase_definitions=[PhaseDefinition(phase_id=PHASE_ID, name="Implement", order=1)],
        )
    )
    return agg


async def _provision_and_run(
    processor,
    *,
    execution_id: str,
    aggregate: WorkflowExecutionAggregate,
    session_id: str,
) -> None:
    """Drive PROVISION_WORKSPACE then RUN_AGENT for one execution's phase.

    Exercises the two real write sites the issue names:
    ``_handle_provision`` (writes ``_phase_started_at``) and
    ``_handle_run_agent`` (writes ``_phase_session_ids``).
    """
    phase = _phase()
    provision_todo = TodoItem(
        execution_id=execution_id, action=TodoAction.PROVISION_WORKSPACE, phase_id=PHASE_ID
    )
    await processor._handle_provision(
        provision_todo,
        phase,
        aggregate,
        repos=None,
        completed_phase_ids=[],
        phase_outputs=PhaseOutputCache(),
    )

    run_todo = TodoItem(
        execution_id=execution_id,
        action=TodoAction.RUN_AGENT,
        phase_id=PHASE_ID,
        session_id=session_id,
    )
    await processor._handle_run_agent(run_todo, phase, aggregate)


async def test_a_second_executions_provision_does_not_corrupt_the_firsts_failure() -> None:
    """Two executions of the same phase id on one processor stay independent.

    Reproduces the issue's own scenario: execution B provisions/runs the same
    phase id AFTER execution A, on the SAME processor instance. Execution A
    then fails. Before the fix, both `_phase_started_at["implement"]` and
    `_phase_session_ids["implement"]` were bare-keyed, so B's write silently
    overwrote A's, and A's failure would report B's session id.
    """
    processor = _make_processor(FakeAgentExecutionHandler.success())
    processor._inputs = {}

    aggregate_a = _started_aggregate("exec-A")
    aggregate_b = _started_aggregate("exec-B")

    await _provision_and_run(
        processor, execution_id="exec-A", aggregate=aggregate_a, session_id="session-A-own"
    )
    # B provisions and runs the SAME phase id on the SAME processor, after A.
    await _provision_and_run(
        processor, execution_id="exec-B", aggregate=aggregate_b, session_id="session-B-own"
    )

    phase_results: list[object] = []
    await processor._fail_execution(
        error=RuntimeError("agent boom"),
        aggregate=aggregate_a,
        execution_id="exec-A",
        workflow_id="wf-shared",
        phases=[_phase()],
        phase_results=phase_results,  # type: ignore[arg-type]
        all_artifact_ids=[],
        completed_phase_ids=[],
        started_at=processor._phase_started_at[("exec-A", PHASE_ID)],
        failed_phase_id=PHASE_ID,
    )

    assert len(phase_results) == 1, "the failed phase must produce a result to count"
    failed = phase_results[0]

    # The value that could ONLY be here if A's own write survived B's write to
    # the same phase id, and A's own read found it.
    assert failed.session_id == "session-A-own"  # type: ignore[attr-defined]

    # B's own state must survive A's failure teardown: a scoped clear removes
    # only A's entries, a blanket clear (the pre-fix `_close_phase_workspace_cms`
    # behaviour for the four infra maps it does touch) would erase B's too.
    assert processor._phase_session_ids[("exec-B", PHASE_ID)] == "session-B-own"
    assert ("exec-B", PHASE_ID) in processor._phase_started_at

    # A's own entries are gone -- the "stale carry-over" half of the issue: a
    # later run reading a dead execution's leftover entry.
    assert ("exec-A", PHASE_ID) not in processor._phase_started_at
    assert ("exec-A", PHASE_ID) not in processor._phase_session_ids
