"""Terminal executions and recorded clock ticks become replay-safe settlement facts."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from event_sourcing import DomainEvent, EventEnvelope, EventMetadata

from syn_domain.contexts.agent_sessions import (
    HostSessionEvidenceProjector,
    InventoryReconciliationSweepEvent,
    SettlementDeadline,
    SettlementDeadlinePage,
)
from syn_domain.contexts.agent_sessions.domain.read_models.session_evidence import (
    RunSettlementStage,
)
from syn_domain.contexts.agent_sessions.ports.SessionEvidenceReadPort import EvidenceBatch
from syn_domain.contexts.agent_sessions.slices.reconcile_session_inventory.execution_settlement import (
    ExecutionTerminalEventType,
)
from syn_domain.contexts.orchestration.domain.events.ExecutionCancelledEvent import (
    ExecutionCancelledEvent,
)
from syn_domain.contexts.orchestration.domain.events.WorkflowCompletedEvent import (
    WorkflowCompletedEvent,
)
from syn_domain.contexts.orchestration.domain.events.WorkflowFailedEvent import WorkflowFailedEvent
from syn_domain.contexts.orchestration.domain.events.WorkflowInterruptedEvent import (
    WorkflowInterruptedEvent,
)

pytestmark = pytest.mark.unit
ENDED = datetime(2026, 9, 25, 12, tzinfo=UTC)


def _real_terminal(kind: ExecutionTerminalEventType, execution_id: str) -> DomainEvent:
    """The actual orchestration event classes, so a renamed event fails here."""
    if kind is ExecutionTerminalEventType.COMPLETED:
        return WorkflowCompletedEvent(
            workflow_id="definition",
            execution_id=execution_id,
            completed_at=ENDED,
            total_phases=1,
            completed_phases=1,
            total_input_tokens=0,
            total_output_tokens=0,
            total_tokens=0,
            total_duration_seconds=1.0,
            artifact_ids=[],
        )
    if kind is ExecutionTerminalEventType.FAILED:
        return WorkflowFailedEvent(
            workflow_id="definition",
            execution_id=execution_id,
            failed_at=ENDED,
            error_message="boom",
            completed_phases=0,
            total_phases=1,
        )
    if kind is ExecutionTerminalEventType.CANCELLED:
        return ExecutionCancelledEvent(
            workflow_id="definition",
            execution_id=execution_id,
            phase_id="phase",
            cancelled_at=ENDED,
        )
    return WorkflowInterruptedEvent(
        workflow_id="definition",
        execution_id=execution_id,
        phase_id="phase",
        interrupted_at=ENDED,
    )


def test_terminal_constants_are_the_real_orchestration_event_names() -> None:
    real = {
        ExecutionTerminalEventType.COMPLETED: WorkflowCompletedEvent,
        ExecutionTerminalEventType.FAILED: WorkflowFailedEvent,
        ExecutionTerminalEventType.CANCELLED: ExecutionCancelledEvent,
        ExecutionTerminalEventType.INTERRUPTED: WorkflowInterruptedEvent,
    }
    assert set(real) == set(ExecutionTerminalEventType)
    for kind, event_class in real.items():
        assert kind == event_class.event_type
        assert _real_terminal(kind, "run").event_type == kind


class _Deadlines:
    def __init__(self) -> None:
        self.rows: dict[str, SettlementDeadline] = {}
        self.settled: set[str] = set()

    async def schedule(self, deadline: SettlementDeadline) -> SettlementDeadline:
        return self.rows.setdefault(deadline.run.execution_id, deadline)

    async def due(self, observed_at: datetime, *, limit: int) -> SettlementDeadlinePage:
        items = [
            row
            for key, row in sorted(self.rows.items())
            if key not in self.settled and row.due_at <= observed_at
        ]
        return SettlementDeadlinePage(items=tuple(items[:limit]))

    async def settle(self, deadline: SettlementDeadline) -> None:
        self.settled.add(deadline.run.execution_id)


def _terminal(
    kind: ExecutionTerminalEventType, *, event_id: str = "end", execution_id: str = "run"
) -> EventEnvelope[DomainEvent]:
    return EventEnvelope(
        event=_real_terminal(kind, execution_id),
        metadata=EventMetadata(
            event_id=event_id,
            timestamp=ENDED,
            aggregate_id=execution_id,
            aggregate_type="WorkflowExecution",
            aggregate_nonce=9,
            global_nonce=40,
            event_type=kind,
        ),
    )


def _sweep(at: datetime) -> EventEnvelope[DomainEvent]:
    return EventEnvelope(
        event=InventoryReconciliationSweepEvent(observed_at=at),
        metadata=EventMetadata(
            event_id=f"tick-{at.isoformat()}",
            aggregate_id="tick",
            aggregate_type="SessionInventoryClock",
            aggregate_nonce=1,
            global_nonce=41,
            event_type=InventoryReconciliationSweepEvent.event_type,
        ),
    )


def _projector(journal: AsyncMock, deadlines: _Deadlines) -> HostSessionEvidenceProjector:
    return HostSessionEvidenceProjector(
        journal, "installation", settlements=deadlines, settlement_grace=timedelta(minutes=5)
    )


@pytest.mark.parametrize("kind", list(ExecutionTerminalEventType))
async def test_every_terminal_status_records_one_replay_stable_fact(
    kind: ExecutionTerminalEventType,
) -> None:
    journal, deadlines = AsyncMock(), _Deadlines()
    projector = _projector(journal, deadlines)
    assert kind in projector.get_subscribed_event_types()
    await projector.handle(_terminal(kind))
    await projector.handle(_terminal(kind))
    first, second = (call.args[0] for call in journal.append.await_args_list)
    assert isinstance(first, EvidenceBatch)
    assert first == second
    assert first.evidence.run.execution_id == "run"
    assert first.evidence.run_settlement[0].stage is RunSettlementStage.EXECUTION_TERMINAL
    assert deadlines.rows["run"].due_at == ENDED + timedelta(minutes=5)


async def test_deadline_is_released_only_by_a_recorded_clock_at_or_after_it() -> None:
    journal, deadlines = AsyncMock(), _Deadlines()
    projector = _projector(journal, deadlines)
    await projector.handle(_terminal(ExecutionTerminalEventType.COMPLETED))
    journal.reset_mock()
    await projector.handle(_sweep(ENDED + timedelta(minutes=4)))
    journal.append.assert_not_awaited()
    await projector.handle(_sweep(ENDED + timedelta(minutes=5)))
    batch = journal.append.await_args.args[0]
    assert isinstance(batch, EvidenceBatch)
    assert batch.evidence.run_settlement[0].stage is RunSettlementStage.SETTLEMENT_DEADLINE
    assert deadlines.settled == {"run"}
    # Later ticks never re-release a settled deadline.
    journal.reset_mock()
    await projector.handle(_sweep(ENDED + timedelta(hours=1)))
    journal.append.assert_not_awaited()


async def test_later_terminal_fact_never_postpones_the_first_deadline() -> None:
    journal, deadlines = AsyncMock(), _Deadlines()
    projector = _projector(journal, deadlines)
    await projector.handle(_terminal(ExecutionTerminalEventType.INTERRUPTED))
    later = _terminal(ExecutionTerminalEventType.FAILED, event_id="later")
    later = later.model_copy(
        update={"metadata": later.metadata.model_copy(update={"timestamp": ENDED + timedelta(1)})}
    )
    await projector.handle(later)
    assert deadlines.rows["run"].due_at == ENDED + timedelta(minutes=5)
    assert journal.append.await_count == 2  # Both facts remain visible evidence.


async def test_crash_between_deadline_fact_and_settle_replays_identically() -> None:
    journal, deadlines = AsyncMock(), _Deadlines()
    await _projector(journal, deadlines).handle(_terminal(ExecutionTerminalEventType.CANCELLED))
    journal.reset_mock()
    tick = _sweep(ENDED + timedelta(minutes=10))
    await _projector(journal, deadlines).handle(tick)
    deadlines.settled.clear()  # settle() never became durable.
    await _projector(journal, deadlines).handle(tick)
    first, second = (call.args[0] for call in journal.append.await_args_list)
    assert first == second


async def test_terminal_without_execution_is_ignored_and_no_port_means_no_deadline() -> None:
    journal = AsyncMock()
    projector = HostSessionEvidenceProjector(journal, "installation")
    assert InventoryReconciliationSweepEvent.event_type not in (
        projector.get_subscribed_event_types()
    )
    await projector.handle(_terminal(ExecutionTerminalEventType.COMPLETED, execution_id=""))
    journal.append.assert_not_awaited()
    await projector.handle(_terminal(ExecutionTerminalEventType.COMPLETED))
    assert journal.append.await_count == 1
    await projector.handle(_sweep(ENDED + timedelta(days=1)))
    assert journal.append.await_count == 1


def test_negative_grace_is_rejected() -> None:
    with pytest.raises(ValueError, match="grace"):
        HostSessionEvidenceProjector(
            AsyncMock(), "installation", settlement_grace=timedelta(seconds=-1)
        )


async def test_replay_under_a_different_grace_setting_yields_identical_facts() -> None:
    deadlines = _Deadlines()
    first_journal, replay_journal = AsyncMock(), AsyncMock()
    terminal = _terminal(ExecutionTerminalEventType.COMPLETED)
    tick = _sweep(ENDED + timedelta(minutes=6))
    first = HostSessionEvidenceProjector(
        first_journal, "installation", settlements=deadlines, settlement_grace=timedelta(minutes=5)
    )
    await first.handle(terminal)
    await first.handle(tick)
    deadlines.settled.clear()  # Rebuild: the to-do is re-derived from recorded events.
    replay = HostSessionEvidenceProjector(
        replay_journal, "installation", settlements=deadlines, settlement_grace=timedelta(hours=9)
    )
    await replay.handle(terminal)
    await replay.handle(tick)
    first_batches = [call.args[0] for call in first_journal.append.await_args_list]
    replay_batches = [call.args[0] for call in replay_journal.append.await_args_list]
    assert len(first_batches) == 2
    assert replay_batches == first_batches
    assert first_batches[0].evidence.run_settlement[0].due_at == ENDED + timedelta(minutes=5)
