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
    _start_and_collect,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    ExecutablePhase,
    ExecutionStatus,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
    WorkflowExecutionAggregate,
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

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]


@pytest.mark.parametrize(
    "pairs",
    [
        [("B", 1), ("A", 1), ("C", 2)],
        [("A", 1), ("B", 1), ("C", 2)],
        [("A", 1), ("A", 2), ("C", 3)],
    ],
)
async def test_invalid_replay_must_not_be_completed_as_success(pairs):
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
    restored = WorkflowExecutionStartedEvent.model_validate_json(event.model_dump_json())
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
    first, order = pairs[0]
    _start_and_collect(aggregate, first, order)
    _complete(aggregate, first)
    projection = ExecutionTodoProjection(store=InMemoryProjectionStore())
    await project_events(
        projection, [restored, *[e.event for e in aggregate.get_uncommitted_events()]]
    )
    aggregate.mark_events_as_committed()
    assert await projection.get_pending(EXECUTION) == []
    repository = AsyncMock()
    processor = WorkflowExecutionProcessor.__new__(WorkflowExecutionProcessor)
    processor._todo_projection = projection
    processor._journal = ExecutionJournal(repository, projection)
    processor._runtimes = MagicMock()
    processor._runtimes.of.return_value.abandon_all = AsyncMock()
    # All sequencing, draining and completion below are production methods.
    # Only unused workspace cleanup, the external repository and the failure
    # recorder (which needs a session repository this path never touches) are
    # doubled; the recorder is asserted on below.
    processor._fail_execution = AsyncMock()
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
    processor._fail_execution.assert_awaited_once()
    refusal = processor._fail_execution.await_args.args[0]
    assert isinstance(refusal, ValueError)
    assert "unordered" in str(refusal)
    events = [e.event for e in aggregate.get_uncommitted_events()]
    assert not [e for e in events if isinstance(e, WorkflowCompletedEvent)]
    assert aggregate.status is not ExecutionStatus.COMPLETED, (
        "Invalid phase order was converted into successful workflow completion with phases unrun"
    )
