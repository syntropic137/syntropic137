"""#1661: each execution's end reaches the sink exactly once, from the live side only."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest
from event_sourcing import DomainEvent, EventEnvelope, EventMetadata
from event_sourcing.stores.memory_checkpoint import MemoryCheckpointStore

from syn_adapters.projection_stores.memory_store import InMemoryProjectionStore
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    FailureClassification,
)
from syn_domain.contexts.orchestration.domain.events.ExecutionCancelledEvent import (
    ExecutionCancelledEvent,
)
from syn_domain.contexts.orchestration.domain.events.WorkflowCompletedEvent import (
    WorkflowCompletedEvent,
)
from syn_domain.contexts.orchestration.domain.events.WorkflowFailedEvent import (
    WorkflowFailedEvent,
)
from syn_domain.contexts.orchestration.slices.notify_execution_lifecycle import (
    ExecutionLifecycleNotice,
    ExecutionLifecycleNoticeProcessManager,
    ExecutionOutcome,
)

pytestmark = pytest.mark.unit

_AT = datetime(2026, 11, 18, 6, 0, tzinfo=UTC)


@dataclass
class _Sink:
    """Records every delivery; refuses the first `refusals` of them."""

    delivered: list[ExecutionLifecycleNotice] = field(default_factory=list)
    refusals: int = 0

    async def deliver(self, notice: ExecutionLifecycleNotice) -> None:
        if self.refusals:
            self.refusals -= 1
            raise ConnectionError("sink unreachable")
        self.delivered.append(notice)


def _completed(execution_id: str = "exec-1") -> WorkflowCompletedEvent:
    return WorkflowCompletedEvent(
        workflow_id="wf-1",
        execution_id=execution_id,
        completed_at=_AT,
        total_phases=2,
        completed_phases=2,
        total_input_tokens=1,
        total_output_tokens=1,
        total_tokens=2,
        total_duration_seconds=3.0,
        artifact_ids=[],
    )


def _failed(execution_id: str = "exec-1") -> WorkflowFailedEvent:
    return WorkflowFailedEvent(
        workflow_id="wf-1",
        execution_id=execution_id,
        failed_at=_AT,
        error_message="phase verify refused the change",
        failure_classification=FailureClassification.TASK,
        completed_phases=1,
        total_phases=3,
    )


def _cancelled(execution_id: str = "exec-1") -> ExecutionCancelledEvent:
    return ExecutionCancelledEvent(
        workflow_id="wf-1",
        execution_id=execution_id,
        phase_id="implement",
        cancelled_at=_AT,
        reason="superseded",
    )


def _envelope(event: DomainEvent, nonce: int = 1) -> EventEnvelope[DomainEvent]:
    return EventEnvelope(
        event=event,
        metadata=EventMetadata(
            aggregate_id="exec-1",
            aggregate_type="WorkflowExecution",
            aggregate_nonce=nonce,
            event_type=type(event).__name__.removesuffix("Event"),
            global_nonce=nonce,
        ),
    )


def _manager(sink: _Sink) -> ExecutionLifecycleNoticeProcessManager:
    return ExecutionLifecycleNoticeProcessManager(sink=sink, store=InMemoryProjectionStore())


async def _handle(manager: ExecutionLifecycleNoticeProcessManager, *events: DomainEvent) -> None:
    for nonce, event in enumerate(events, start=1):
        await manager.handle_event(_envelope(event, nonce), MemoryCheckpointStore())


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("event", "outcome"),
    [
        (_completed(), ExecutionOutcome.COMPLETED),
        (_failed(), ExecutionOutcome.FAILED),
        (_cancelled(), ExecutionOutcome.CANCELLED),
    ],
)
async def test_each_terminal_event_delivers_exactly_one_notice(
    event: DomainEvent, outcome: ExecutionOutcome
) -> None:
    sink = _Sink()
    manager = _manager(sink)
    await _handle(manager, event)

    assert await manager.process_pending() == 1
    assert await manager.process_pending() == 0
    assert [(n.execution_id, n.outcome) for n in sink.delivered] == [("exec-1", outcome)]


@pytest.mark.asyncio
async def test_catch_up_alone_delivers_nothing() -> None:
    sink = _Sink()
    manager = _manager(sink)
    # handle_event is all a catch-up replay ever calls.
    await _handle(manager, _completed(), _failed("exec-2"), _cancelled("exec-3"))
    await _handle(manager, _completed(), _failed("exec-2"), _cancelled("exec-3"))

    assert sink.delivered == []


@pytest.mark.asyncio
async def test_replaying_after_delivery_delivers_nothing() -> None:
    sink = _Sink()
    manager = _manager(sink)
    await _handle(manager, _completed(), _failed("exec-2"))
    assert await manager.process_pending() == 2

    # A rebuild replays the same history; the delivered records must stay delivered.
    await _handle(manager, _completed(), _failed("exec-2"))

    assert await manager.process_pending() == 0
    assert len(sink.delivered) == 2


@pytest.mark.asyncio
async def test_a_refused_delivery_stays_owed_and_the_next_pass_delivers_it_once() -> None:
    sink = _Sink(refusals=1)
    manager = _manager(sink)
    await _handle(manager, _failed())

    assert await manager.process_pending() == 0
    assert sink.delivered == []

    assert await manager.process_pending() == 1
    assert await manager.process_pending() == 0
    assert [n.outcome for n in sink.delivered] == [ExecutionOutcome.FAILED]


@pytest.mark.asyncio
async def test_two_outcomes_for_one_execution_are_two_notices() -> None:
    sink = _Sink()
    manager = _manager(sink)
    # Failed, then resumed and completed: the same execution id ends twice.
    await _handle(manager, _failed(), _completed())

    assert await manager.process_pending() == 2
    assert sorted(n.outcome for n in sink.delivered) == sorted(
        [ExecutionOutcome.FAILED, ExecutionOutcome.COMPLETED]
    )
    assert {n.execution_id for n in sink.delivered} == {"exec-1"}


def test_the_clock_tick_wakes_it_so_an_owed_notice_is_retried_on_a_quiet_system() -> None:
    subscribed = _manager(_Sink()).get_subscribed_event_types()

    assert subscribed == {
        "WorkflowCompleted",
        "WorkflowFailed",
        "ExecutionCancelled",
        "InventoryReconciliationSweep",
    }
