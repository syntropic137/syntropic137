"""An execution whose replayed phases are not a total order must not drain to success (#1455).

Crosses the typed start event, the real to-do projection and the processor's
drain, because the aggregate alone cannot show the empty to-do list that the
processor reads as "nothing left to run".
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from event_sourcing import EventEnvelope, EventMetadata

from syn_adapters.projection_stores.memory_store import InMemoryProjectionStore
from syn_domain.contexts.orchestration.domain.aggregate_execution.test_phase_order_total import (
    EXECUTION,
    _complete,
    _recorded_start_and_collect,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    ExecutablePhase,
    ExecutionStatus,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
    WorkflowExecutionAggregate,
)
from syn_domain.contexts.orchestration.domain.events.PhaseStartedEvent import (
    PhaseStartedEvent,
)
from syn_domain.contexts.orchestration.domain.events.WorkflowCompletedEvent import (
    WorkflowCompletedEvent,
)
from syn_domain.contexts.orchestration.domain.events.WorkflowExecutionStartedEvent import (
    WorkflowExecutionStartedEvent,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.execution_journal import (
    ExecutionJournal,
    project_events,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.phase_workspace import (
    PhaseWorkspace,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.processor_types import (
    PhaseOutputCache,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.WorkflowExecutionProcessor import (
    WorkflowExecutionProcessor,
    _DispatchContext,
)
from syn_domain.contexts.orchestration.slices.execution_todo.projection import (
    ExecutionTodoProjection,
)
from syn_domain.contexts.orchestration.slices.execution_todo.value_objects import (
    TodoAction,
    TodoItem,
)

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]


UNORDERED = pytest.mark.parametrize(
    "pairs",
    [
        [("B", 1), ("A", 1), ("C", 2)],
        [("A", 1), ("B", 1), ("C", 2)],
        [("A", 1), ("A", 2), ("C", 3)],
    ],
    ids=["tied-orders-B-first", "tied-orders-A-first", "duplicate-phase-ids"],
)


def _start_event(pairs) -> WorkflowExecutionStartedEvent:
    event = WorkflowExecutionStartedEvent(
        workflow_id="wf-1",
        execution_id=EXECUTION,
        workflow_name="probe",
        started_at=datetime.now(UTC),
        total_phases=3,
        inputs={},
        phase_definitions=[
            {"phase_id": p, "name": p, "order": o, "timeout_seconds": 300} for p, o in pairs
        ],
        pinned_phases=[ExecutablePhase(phase_id=p, name=p, order=o) for p, o in pairs],
    )
    # Full pinned shape, through the typed event's real serialization/conversion.
    return WorkflowExecutionStartedEvent.model_validate_json(event.model_dump_json())


def _rehydrated(restored: WorkflowExecutionStartedEvent) -> WorkflowExecutionAggregate:
    aggregate = WorkflowExecutionAggregate()
    aggregate.rehydrate(
        [
            EventEnvelope(
                event=restored,
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


def _processor(projection: ExecutionTodoProjection) -> WorkflowExecutionProcessor:
    processor = WorkflowExecutionProcessor.__new__(WorkflowExecutionProcessor)
    processor._todo_projection = projection
    processor._journal = ExecutionJournal(AsyncMock(), projection)
    processor._runtimes = MagicMock()
    processor._runtimes.of.return_value.abandon_all = AsyncMock()
    # The failure recorder needs a session repository this path never
    # touches; it is doubled and asserted on.
    processor._fail_execution = AsyncMock()
    return processor


async def _drain(processor: WorkflowExecutionProcessor, aggregate: WorkflowExecutionAggregate):
    await processor._drain(
        aggregate,
        "wf-1",
        aggregate.start_pins.pinned_phases,
        _DispatchContext(),
        None,
        None,
        PhaseOutputCache(),
        datetime.now(UTC),
    )


def _assert_failed_unrun(processor: WorkflowExecutionProcessor, aggregate) -> None:
    processor._fail_execution.assert_awaited_once()
    refusal = processor._fail_execution.await_args.args[0]
    assert isinstance(refusal, ValueError)
    assert "unordered" in str(refusal)
    events = [e.event for e in aggregate.get_uncommitted_events()]
    assert not [e for e in events if isinstance(e, PhaseStartedEvent)]
    assert not [e for e in events if isinstance(e, WorkflowCompletedEvent)]
    assert aggregate.status is not ExecutionStatus.COMPLETED


@UNORDERED
async def test_an_unordered_start_alone_schedules_no_phase(pairs):
    """The start is the first scheduling decision; nothing may precede it here."""
    restored = _start_event(pairs)
    aggregate = _rehydrated(restored)
    projection = ExecutionTodoProjection(store=InMemoryProjectionStore())
    await project_events(projection, [restored])
    assert await projection.get_pending(EXECUTION) == []
    processor = _processor(projection)
    processor._workspaces_for = MagicMock()
    await _drain(processor, aggregate)
    processor._workspaces_for.assert_not_called()
    _assert_failed_unrun(processor, aggregate)


@UNORDERED
async def test_a_phase_already_queued_for_an_unordered_start_is_not_run(pairs):
    """A to-do record written before the projection refused the list still holds work."""
    restored = _start_event(pairs)
    aggregate = _rehydrated(restored)
    projection = ExecutionTodoProjection(store=InMemoryProjectionStore())
    queued = pairs[0][0]
    await projection._advance_phase_todo(
        EXECUTION,
        queued,
        TodoItem(execution_id=EXECUTION, action=TodoAction.PROVISION_WORKSPACE, phase_id=queued),
    )
    workspace = PhaseWorkspace.__new__(PhaseWorkspace)
    workspace.provision = AsyncMock()
    processor = _processor(projection)
    processor._workspaces_for = MagicMock(return_value=workspace)
    await _drain(processor, aggregate)
    workspace.provision.assert_not_awaited()
    _assert_failed_unrun(processor, aggregate)


@UNORDERED
async def test_invalid_replay_must_not_be_completed_as_success(pairs):
    restored = _start_event(pairs)
    aggregate = _rehydrated(restored)
    first, order = pairs[0]
    _recorded_start_and_collect(aggregate, first, order)
    _complete(aggregate, first)
    projection = ExecutionTodoProjection(store=InMemoryProjectionStore())
    await project_events(
        projection, [restored, *[e.event for e in aggregate.get_uncommitted_events()]]
    )
    aggregate.mark_events_as_committed()
    assert await projection.get_pending(EXECUTION) == []
    processor = _processor(projection)
    await _drain(processor, aggregate)
    _assert_failed_unrun(processor, aggregate)
