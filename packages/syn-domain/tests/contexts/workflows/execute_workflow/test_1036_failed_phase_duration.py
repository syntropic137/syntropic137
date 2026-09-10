"""Regression tests for #1036: a failed phase reported duration_seconds 0.0.

A phase that fails (timeout, non-zero exit) never reaches
``_handle_complete_phase`` -- the only place that used to compute a phase's
elapsed time -- so every consumer of phase duration fell back to whatever
default it was seeded with:

- ``WorkflowExecutionDetailProjection``: stuck at the 0.0 ``PhaseDetail.running()``
  seeds a phase with, and ``total_duration_seconds`` under-reported by exactly
  the failed phase's time since it never entered the accumulation.
- ``WorkflowPhaseMetricsProjection``: had no ``on_workflow_failed`` handler at
  all, so the phase stayed "running" forever with duration_seconds 0.0.

These tests drive the real ``WorkflowExecutionProcessor._fail_execution``
(the actual failure path, not a reimplementation of it) with a controlled,
deliberately non-round elapsed time, then feed the resulting
``WorkflowFailedEvent`` -- serialized exactly as production does via
``_serialize_event`` -- into fresh instances of both consumer projections and
assert on the stored rows, not on the event object.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from syn_adapters.projection_stores.memory_store import InMemoryProjectionStore
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    ExecutablePhase,
    PhaseDefinition,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
    StartExecutionCommand,
    StartPhaseCommand,
    WorkflowExecutionAggregate,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.execution_journal import (
    ExecutionJournal,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.WorkflowExecutionProcessor import (
    WorkflowExecutionProcessor,
)
from syn_domain.contexts.orchestration.slices.execution_todo.projection import (
    ExecutionTodoProjection,
)
from syn_domain.contexts.orchestration.slices.get_execution_detail.projection import (
    WorkflowExecutionDetailProjection,
)
from syn_domain.contexts.orchestration.slices.workflow_phase_metrics.projection import (
    WorkflowPhaseMetricsProjection,
)

#: Deliberately non-round and far from both 0.0 and any value a stub would
#: produce by accident (e.g. a rounded timeout like 1800.0). If the duration
#: plumbing regresses to a hardcoded/default value, this exact figure will
#: not appear in either projection's stored row.
FIXTURE_DURATION_SECONDS = 137.25


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


def _make_running_aggregate(execution_id: str = "exec-1") -> WorkflowExecutionAggregate:
    agg = WorkflowExecutionAggregate()
    agg._handle_command(
        StartExecutionCommand(
            execution_id=execution_id,
            workflow_id="wf-1",
            workflow_name="Test Workflow",
            total_phases=1,
            inputs={},
            phase_definitions=[PhaseDefinition(phase_id="p-1", name="Phase 1", order=1)],
        )
    )
    agg._handle_command(
        StartPhaseCommand(
            execution_id=execution_id,
            workflow_id="wf-1",
            phase_id="p-1",
            phase_name="Phase 1",
            phase_order=1,
        )
    )
    return agg


async def _run_fail_execution_and_serialize(processor: WorkflowExecutionProcessor) -> dict:
    """Drive the real failure path and return the serialized WorkflowFailedEvent.

    Mirrors what a timed-out phase looks like in production: the phase was
    dispatched (so the runtime holds its start time) and then the
    run raised, with the elapsed time fixed to FIXTURE_DURATION_SECONDS
    rather than depending on real wall-clock sleeps (no freezegun available
    in this repo).
    """
    aggregate = _make_running_aggregate("exec-1")
    # no-op: keep uncommitted events for inspection
    processor._journal._repository.save = AsyncMock()  # pyright: ignore[reportPrivateUsage]

    fixed_started_at = datetime.now(UTC) - timedelta(seconds=FIXTURE_DURATION_SECONDS)
    processor._runtime._started_at["p-1"] = fixed_started_at  # pyright: ignore[reportPrivateUsage]

    phases = [ExecutablePhase(phase_id="p-1", name="Phase 1", order=1)]

    await processor._fail_execution(
        error=RuntimeError("Agent execution failed for phase p-1 (exit_code=124)"),
        aggregate=aggregate,
        execution_id="exec-1",
        workflow_id="wf-1",
        phases=phases,
        phase_results=[],
        all_artifact_ids=[],
        completed_phase_ids=[],
        started_at=fixed_started_at,
        failed_phase_id="p-1",
    )

    failed_events = [
        envelope.event
        for envelope in aggregate.get_uncommitted_events()
        if type(envelope.event).__name__ == "WorkflowFailedEvent"
    ]
    assert len(failed_events) == 1, (
        "expected _fail_execution to emit exactly one WorkflowFailedEvent"
    )
    return ExecutionJournal._serialize_event(failed_events[0])


@pytest.mark.unit
@pytest.mark.anyio
class TestFailedPhaseDurationDetailProjection:
    """WorkflowExecutionDetailProjection is the get_execution_detail API's read model."""

    async def test_failed_phase_reports_real_duration_not_zero(self) -> None:
        processor = _make_processor()
        event_data = await _run_fail_execution_and_serialize(processor)

        detail = WorkflowExecutionDetailProjection(InMemoryProjectionStore())
        await detail.on_workflow_execution_started(
            {"execution_id": "exec-1", "workflow_id": "wf-1", "workflow_name": "Test Workflow"}
        )
        await detail.on_phase_started(
            {"execution_id": "exec-1", "phase_id": "p-1", "phase_name": "Phase 1"}
        )

        await detail.on_workflow_failed(event_data)

        row = await detail._store.get(detail.PROJECTION_NAME, "exec-1")
        assert row is not None
        phase = next(p for p in row["phases"] if p["phase_id"] == "p-1")
        assert phase["status"] == "failed"
        assert phase["duration_seconds"] == pytest.approx(FIXTURE_DURATION_SECONDS, abs=1.0)

    async def test_failed_phase_duration_rolls_into_execution_total(self) -> None:
        processor = _make_processor()
        event_data = await _run_fail_execution_and_serialize(processor)

        detail = WorkflowExecutionDetailProjection(InMemoryProjectionStore())
        await detail.on_workflow_execution_started(
            {"execution_id": "exec-1", "workflow_id": "wf-1", "workflow_name": "Test Workflow"}
        )
        await detail.on_phase_started(
            {"execution_id": "exec-1", "phase_id": "p-1", "phase_name": "Phase 1"}
        )

        await detail.on_workflow_failed(event_data)

        row = await detail._store.get(detail.PROJECTION_NAME, "exec-1")
        assert row is not None
        assert row["total_duration_seconds"] == pytest.approx(FIXTURE_DURATION_SECONDS, abs=1.0)


@pytest.mark.unit
@pytest.mark.anyio
class TestFailedPhaseDurationMetricsProjection:
    """WorkflowPhaseMetricsProjection backs GET /metrics?workflow_id=."""

    async def test_failed_phase_marked_failed_with_real_duration(self) -> None:
        processor = _make_processor()
        event_data = await _run_fail_execution_and_serialize(processor)

        metrics = WorkflowPhaseMetricsProjection(InMemoryProjectionStore())
        # Same execution the WorkflowFailed event names: the metrics projection
        # aggregates across executions, so it closes the run of the execution
        # that failed, not whichever run of the phase happens to be open.
        await metrics.on_phase_started(
            {
                "workflow_id": "wf-1",
                "execution_id": "exec-1",
                "phase_id": "p-1",
                "phase_name": "Phase 1",
            }
        )

        await metrics.on_workflow_failed(event_data)

        phases = await metrics.get_phase_metrics("wf-1")
        assert phases["p-1"].status == "failed"
        assert phases["p-1"].duration_seconds() == pytest.approx(FIXTURE_DURATION_SECONDS, abs=1.0)
