"""Regression test for #1044: phase timing/session maps keyed by phase_id alone.

``WorkflowExecutionProcessor`` is shared across concurrent executions
(``BackgroundWorkflowDispatcher`` dispatches up to ``max_concurrent`` runs on
one processor instance), and ``phase_id`` is unique within a workflow
definition, not within a deployment. Two executions of the same workflow
running at once dispatch the same phase_id, so a map keyed by phase_id alone
lets the second execution's write silently answer the first's read.

This drives the real consumer -- ``WorkflowExecutionProcessor._fail_execution``,
which is what actually reads ``_phase_started_at`` / ``_phase_session_ids`` to
build the failed phase's result -- rather than asserting on the maps
themselves. Before #1044, seeding both executions' entries under the bare
phase_id key left only the second execution's values in the dict (the first
was silently overwritten), so execution A's failure would report execution
B's start time and session id. It would also wipe execution B's still-live
entries when A's failure path tore its workspaces down, per the "stale
carry-over" half of the issue.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from syn_adapters.projection_stores.memory_store import InMemoryProjectionStore
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    ExecutablePhase,
    PhaseDefinition,
    PhaseResult,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
    StartExecutionCommand,
    StartPhaseCommand,
    WorkflowExecutionAggregate,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.WorkflowExecutionProcessor import (
    WorkflowExecutionProcessor,
)
from syn_domain.contexts.orchestration.slices.execution_todo.projection import (
    ExecutionTodoProjection,
)

#: Shared by both executions on purpose -- the whole hazard is that phase_id
#: alone is not unique across concurrent executions of the same workflow.
PHASE_ID = "implement"

#: Non-round, and sharing no factor with each other or with 0: neither can
#: arise from the other, from a default, or from reading the wrong entry by
#: coincidence.
DURATION_A_SECONDS = 137.25
DURATION_B_SECONDS = 9.5


def _make_processor() -> WorkflowExecutionProcessor:
    return WorkflowExecutionProcessor(
        execution_repository=AsyncMock(),
        session_repository=AsyncMock(),
        workspace_service=MagicMock(),
        artifact_repository=AsyncMock(),
        artifact_content_storage=None,
        artifact_query=None,
        conversation_storage=None,
        observability_writer=None,
        controller=None,
        prompt_builder=AsyncMock(return_value="test prompt"),
        command_builder=MagicMock(return_value=["claude", "--model", "haiku"]),
        todo_projection=ExecutionTodoProjection(store=InMemoryProjectionStore()),
    )


def _make_running_aggregate(execution_id: str) -> WorkflowExecutionAggregate:
    agg = WorkflowExecutionAggregate()
    agg._handle_command(
        StartExecutionCommand(
            execution_id=execution_id,
            workflow_id="wf-1",
            workflow_name="Test Workflow",
            total_phases=1,
            inputs={},
            phase_definitions=[PhaseDefinition(phase_id=PHASE_ID, name="Implement", order=1)],
        )
    )
    agg._handle_command(
        StartPhaseCommand(
            execution_id=execution_id,
            workflow_id="wf-1",
            phase_id=PHASE_ID,
            phase_name="Implement",
            phase_order=1,
        )
    )
    return agg


@pytest.mark.unit
@pytest.mark.anyio
async def test_a_failed_execution_reports_its_own_duration_and_session_not_a_concurrent_peers() -> (
    None
):
    """exec-A's failure must read exec-A's start time and session id.

    Both executions provisioned the same phase_id on the shared processor
    before either failed -- exactly what happens when two runs of the same
    workflow definition are in flight together.
    """
    processor = _make_processor()
    processor._execution_repo.save = AsyncMock()  # keep uncommitted events for inspection

    now = datetime.now(UTC)
    started_a = now - timedelta(seconds=DURATION_A_SECONDS)
    started_b = now - timedelta(seconds=DURATION_B_SECONDS)

    processor._phase_started_at[("exec-A", PHASE_ID)] = started_a
    processor._phase_started_at[("exec-B", PHASE_ID)] = started_b
    processor._phase_session_ids[("exec-A", PHASE_ID)] = "sess-A"
    processor._phase_session_ids[("exec-B", PHASE_ID)] = "sess-B"

    results_a: list[PhaseResult] = []
    await processor._fail_execution(
        error=RuntimeError("Agent execution failed for phase implement (exit_code=124)"),
        aggregate=_make_running_aggregate("exec-A"),
        execution_id="exec-A",
        workflow_id="wf-1",
        phases=[ExecutablePhase(phase_id=PHASE_ID, name="Implement", order=1)],
        phase_results=results_a,
        all_artifact_ids=[],
        completed_phase_ids=[],
        started_at=started_a,
        failed_phase_id=PHASE_ID,
    )

    assert len(results_a) == 1, "the failed phase must produce a result to count"
    failed_a = results_a[0]

    # Could only be "sess-A" if the lookup was scoped to exec-A: a phase-only
    # key returns whichever execution wrote last, which is exec-B here.
    assert failed_a.session_id == "sess-A"
    assert failed_a.started_at == started_a
    assert failed_a.completed_at is not None
    elapsed = (failed_a.completed_at - failed_a.started_at).total_seconds()
    assert elapsed == pytest.approx(DURATION_A_SECONDS, abs=1.0)

    # exec-B's own entries must survive exec-A's teardown untouched: the
    # "stale carry-over" half of #1044 is a terminal path blanking state a
    # concurrently running execution still needs.
    assert processor._phase_started_at[("exec-B", PHASE_ID)] == started_b
    assert processor._phase_session_ids[("exec-B", PHASE_ID)] == "sess-B"
