"""Terminal executions and recorded clock ticks become replay-safe settlement facts."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from event_sourcing import DomainEvent, EventEnvelope, EventMetadata

from syn_domain.contexts.agent_sessions import (
    HostSessionEvidenceProjector,
    InventoryReconciliationProcessManager,
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
        self.clock: datetime | None = None

    async def schedule(self, deadline: SettlementDeadline) -> SettlementDeadline:
        return self.rows.setdefault(deadline.run.execution_id, deadline)

    async def observe_clock(self, observed_at: datetime) -> None:
        self.clock = observed_at if self.clock is None else max(self.clock, observed_at)

    async def due(self, *, limit: int) -> SettlementDeadlinePage:
        clock = self.clock
        if clock is None:
            return SettlementDeadlinePage(items=())
        items = [
            row
            for key, row in sorted(self.rows.items())
            if key not in self.settled and row.due_at <= clock
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


def _processor(projector: HostSessionEvidenceProjector) -> InventoryReconciliationProcessManager:
    jobs = AsyncMock()
    jobs.claim.return_value = None
    return InventoryReconciliationProcessManager(
        jobs,
        AsyncMock(),
        lease_seconds=30,
        retry_seconds=1,
        max_jobs_per_tick=1,
        host_evidence=projector,
    )


def _deadline_facts(journal: AsyncMock) -> list[EvidenceBatch]:
    return [
        call.args[0]
        for call in journal.append.await_args_list
        if call.args[0].evidence.run_settlement
        and call.args[0].evidence.run_settlement[0].stage is RunSettlementStage.SETTLEMENT_DEADLINE
    ]


async def _catch_up(
    manager: InventoryReconciliationProcessManager, *events: EventEnvelope[DomainEvent]
) -> None:
    for envelope in events:
        await manager.handle_event(envelope, AsyncMock())


async def test_catch_up_records_the_clock_but_releases_nothing() -> None:
    journal, deadlines = AsyncMock(), _Deadlines()
    manager = _processor(_projector(journal, deadlines))
    await _catch_up(
        manager,
        _terminal(ExecutionTerminalEventType.COMPLETED),
        _sweep(ENDED + timedelta(minutes=4)),
        _sweep(ENDED + timedelta(hours=1)),
        _sweep(ENDED + timedelta(minutes=2)),  # Out-of-order ticks never move it back.
    )
    assert _deadline_facts(journal) == []
    assert deadlines.settled == set()
    assert deadlines.clock == ENDED + timedelta(hours=1)
    await manager.process_pending()  # Live only: the coordinator's boundary.
    released = _deadline_facts(journal)
    assert len(released) == 1
    assert released[0].evidence.run_settlement[0].due_at == ENDED + timedelta(minutes=5)
    assert deadlines.settled == {"run"}
    await manager.process_pending()
    assert len(_deadline_facts(journal)) == 1  # Exactly once.


async def test_recorded_clock_before_the_deadline_releases_nothing_live() -> None:
    journal, deadlines = AsyncMock(), _Deadlines()
    manager = _processor(_projector(journal, deadlines))
    await _catch_up(
        manager,
        _terminal(ExecutionTerminalEventType.COMPLETED),
        _sweep(ENDED + timedelta(minutes=4)),
    )
    await manager.process_pending()
    assert _deadline_facts(journal) == []
    await _catch_up(manager, _sweep(ENDED + timedelta(minutes=5)))
    await manager.process_pending()
    assert len(_deadline_facts(journal)) == 1


async def test_replaying_twice_yields_the_same_facts() -> None:
    events = (
        _terminal(ExecutionTerminalEventType.FAILED),
        _sweep(ENDED + timedelta(minutes=9)),
    )
    runs = []
    for _ in range(2):
        journal, deadlines = AsyncMock(), _Deadlines()
        manager = _processor(_projector(journal, deadlines))
        await _catch_up(manager, *events)
        await manager.process_pending()
        runs.append([call.args[0] for call in journal.append.await_args_list])
    assert runs[0] == runs[1]
    assert len(runs[0]) == 2


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
    projector = _projector(journal, deadlines)
    await projector.handle(_terminal(ExecutionTerminalEventType.CANCELLED))
    await projector.handle(_sweep(ENDED + timedelta(minutes=10)))
    journal.reset_mock()
    await projector.release_deadlines()
    deadlines.settled.clear()  # settle() never became durable.
    await projector.release_deadlines()
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
    assert await projector.release_deadlines() == 0
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
    await first.release_deadlines()
    deadlines.settled.clear()  # Rebuild: the to-do is re-derived from recorded events.
    replay = HostSessionEvidenceProjector(
        replay_journal, "installation", settlements=deadlines, settlement_grace=timedelta(hours=9)
    )
    await replay.handle(terminal)
    await replay.handle(tick)
    await replay.release_deadlines()
    first_batches = [call.args[0] for call in first_journal.append.await_args_list]
    replay_batches = [call.args[0] for call in replay_journal.append.await_args_list]
    assert len(first_batches) == 2
    assert replay_batches == first_batches
    assert first_batches[0].evidence.run_settlement[0].due_at == ENDED + timedelta(minutes=5)
