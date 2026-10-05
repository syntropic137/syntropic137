"""#1547: a quarantine reaches the PR exactly once, from the live side only."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
from event_sourcing import DomainEvent, EventEnvelope, EventMetadata
from event_sourcing.stores.memory_checkpoint import MemoryCheckpointStore
from event_sourcing.subscriptions.coordinator import SubscriptionCoordinator

from syn_adapters.projection_stores.memory_store import InMemoryProjectionStore
from syn_domain.contexts.agent_sessions import InventoryReconciliationSweepEvent
from syn_domain.contexts.orchestration.domain.aggregate_execution.branch_continuation import (
    RemoteBranchReading,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.commands import (
    CancelExecutionCommand,
    FailExecutionCommand,
    RecordCancelledWorkCommand,
    StartExecutionCommand,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.lifecycle_events import (
    failed_event,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    FailureClassification,
    PhaseDefinition,
    QuarantinedRef,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
    WorkflowExecutionAggregate,
)
from syn_domain.contexts.orchestration.slices.execute_workflow import cancelled_work_record
from syn_domain.contexts.orchestration.slices.execute_workflow.cancelled_work_record import (
    OWED_CANCELLED_WORK,
    CancelledWorkLedger,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.execution_journal import (
    ExecutionJournal,
)
from syn_domain.contexts.orchestration.slices.notify_quarantine import (
    QuarantineNoticeProcessManager,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

REF = "refs/syn/lost/exec-q1/implement"
SHA = "a1b2c3d4e5f60718293a4b5c6d7e8f9012345678"


@dataclass
class _Commenter:
    """A forge that remembers comments by id, as GitHub does."""

    comments: dict[int, str] = field(default_factory=dict)
    posts: int = 0
    edits: int = 0
    repository: str = "acme/widget"

    async def upsert_comment(
        self, repository: str, pull_request: int, *, marker: str, body: str, comment_id: int | None
    ) -> int:
        assert repository == self.repository
        assert pull_request == 42
        assert body.startswith(marker)
        if comment_id is not None:
            self.edits += 1
            self.comments[comment_id] = body
            return comment_id
        self.posts += 1
        new_id = 9000 + self.posts
        self.comments[new_id] = body
        return new_id


@dataclass
class _Forge:
    open_pr: int | None = None

    async def read_branch(self, repository: str, branch: str) -> RemoteBranchReading:
        return RemoteBranchReading(
            repository=repository, branch=branch, readable=True, open_pull_request=self.open_pr
        )


def _failed(*, commit: str = SHA, pull_request: int | None = 42, nonce: int = 1) -> EventEnvelope:
    """The event as the aggregate builds it, so a hop that drops the refs fails here."""
    command = FailExecutionCommand(
        execution_id="exec-q1",
        error="phase timed out",
        error_type="TimeoutError",
        failed_phase_id="implement",
        completed_phases=0,
        total_phases=1,
        classification=FailureClassification.UNCLASSIFIED,
        quarantined=(
            QuarantinedRef(
                repository="acme/widget",
                branch="feat/thing",
                ref=REF,
                commit=commit,
                commit_count=2,
                pull_request=pull_request,
            ),
        ),
    )
    event = failed_event(command, "wf-1")
    return EventEnvelope(
        event=event,
        metadata=EventMetadata(
            aggregate_id="exec-q1",
            aggregate_type="WorkflowExecution",
            aggregate_nonce=nonce,
            event_type="WorkflowFailed",
            global_nonce=nonce,
        ),
    )


def _manager(forge: _Forge | None = None) -> tuple[QuarantineNoticeProcessManager, _Commenter]:
    commenter = _Commenter()
    return (
        QuarantineNoticeProcessManager(
            commenter=commenter, store=InMemoryProjectionStore(), branches=forge
        ),
        commenter,
    )


@pytest.mark.asyncio
async def test_replaying_the_quarantine_posts_nothing() -> None:
    manager, commenter = _manager()
    for _ in range(3):
        await manager.handle_event(_failed(), MemoryCheckpointStore())
    # handle_event is all a catch-up replay ever calls.
    assert commenter.posts == 0 and commenter.edits == 0


@pytest.mark.asyncio
async def test_live_posts_exactly_once_naming_ref_sha_phase_and_fetch() -> None:
    manager, commenter = _manager()
    await manager.handle_event(_failed(), MemoryCheckpointStore())
    assert await manager.process_pending() == 1
    # A second pass, and the same event replayed after it, owe nothing more.
    assert await manager.process_pending() == 0
    await manager.handle_event(_failed(), MemoryCheckpointStore())
    assert await manager.process_pending() == 0
    assert commenter.posts == 1 and commenter.edits == 0
    (body,) = commenter.comments.values()
    assert REF in body and SHA in body and "`implement`" in body
    assert f"git fetch origin {REF}:refs/heads/recovered/exec-q1/implement" in body
    assert "/workspace" not in body and "token" not in body.lower()


@pytest.mark.asyncio
async def test_a_retry_updates_the_same_comment() -> None:
    manager, commenter = _manager()
    await manager.handle_event(_failed(), MemoryCheckpointStore())
    await manager.process_pending()
    retried = "f" * 40
    await manager.handle_event(_failed(commit=retried, nonce=2), MemoryCheckpointStore())
    assert await manager.process_pending() == 1
    assert commenter.posts == 1 and commenter.edits == 1
    assert list(commenter.comments) == [9001]
    assert retried in commenter.comments[9001]


@pytest.mark.asyncio
async def test_with_no_pr_yet_it_posts_once_one_opens() -> None:
    forge = _Forge()
    manager, commenter = _manager(forge)
    await manager.handle_event(_failed(pull_request=None), MemoryCheckpointStore())
    assert await manager.process_pending() == 0
    assert commenter.posts == 0
    forge.open_pr = 42
    assert await manager.process_pending() == 1
    assert commenter.posts == 1


@pytest.mark.asyncio
async def test_a_pr_opening_long_after_the_failure_still_gets_the_notice() -> None:
    forge = _Forge()
    manager, commenter = _manager(forge)
    envelope = _failed(pull_request=None)
    old = envelope.event.model_copy(update={"failed_at": datetime.now(UTC) - timedelta(days=30)})
    await manager.handle_event(
        EventEnvelope(event=old, metadata=envelope.metadata), MemoryCheckpointStore()
    )
    assert await manager.process_pending() == 0
    forge.open_pr = 42
    assert await manager.process_pending() == 1
    assert commenter.posts == 1


class _LiveStore:
    """One history, fanned out live to the coordinator, as the gRPC feed is."""

    def __init__(self) -> None:
        self._events: list[EventEnvelope] = []
        self._listeners: list[asyncio.Queue[EventEnvelope]] = []
        self.subscribed = asyncio.Event()

    def publish(self, event: DomainEvent, event_type: str) -> None:
        nonce = len(self._events) + 1
        envelope = EventEnvelope(
            event=event,
            metadata=EventMetadata(
                aggregate_id=f"agg-{nonce}",
                aggregate_type="Any",
                aggregate_nonce=1,
                event_type=event_type,
                global_nonce=nonce,
            ),
        )
        self._events.append(envelope)
        for queue in self._listeners:
            queue.put_nowait(envelope)

    async def read_all(
        self, from_global_nonce: int = 0, max_count: int = 100, forward: bool = True
    ) -> tuple[list[EventEnvelope], bool, int]:
        if not forward:
            return list(reversed(self._events))[:max_count], True, 0
        return self._events[max(from_global_nonce - 1, 0) :][:max_count], True, 0

    async def subscribe(self, from_global_nonce: int) -> AsyncIterator[EventEnvelope]:
        queue: asyncio.Queue[EventEnvelope] = asyncio.Queue()
        self._listeners.append(queue)
        self.subscribed.set()
        try:
            while True:
                envelope = await queue.get()
                if (envelope.metadata.global_nonce or 0) >= from_global_nonce:
                    yield envelope
        finally:
            self._listeners.remove(queue)


@pytest.mark.asyncio
async def test_a_pr_opened_on_a_quiet_system_is_told_on_the_next_clock_tick() -> None:
    """Through the real coordinator: nothing here calls `process_pending()`.

    After the failure nothing in the run happens again - no phase, no resume -
    so the only thing that can wake the notice is the platform's clock.
    """
    forge = _Forge()
    manager, commenter = _manager(forge)
    store = _LiveStore()
    checkpoints = MemoryCheckpointStore()
    coordinator = SubscriptionCoordinator(
        event_store=store, checkpoint_store=checkpoints, projections=[manager]
    )
    runner = asyncio.create_task(coordinator.start())
    try:
        await asyncio.wait_for(store.subscribed.wait(), 5)
        store.publish(_failed(pull_request=None).event, "WorkflowFailed")
        await asyncio.wait_for(_settled(coordinator, checkpoints, 1), 5)
        assert commenter.posts == 0

        forge.open_pr = 42
        store.publish(InventoryReconciliationSweepEvent(observed_at=datetime.now(UTC)), _TICK)
        await asyncio.wait_for(_settled(coordinator, checkpoints, 2), 5)
        assert commenter.posts == 1
    finally:
        await coordinator.stop()
        runner.cancel()
        await asyncio.gather(runner, return_exceptions=True)


_TICK = "InventoryReconciliationSweep"


async def _settled(
    coordinator: SubscriptionCoordinator, checkpoints: MemoryCheckpointStore, nonce: int
) -> None:
    while True:
        checkpoint = await checkpoints.get_checkpoint(
            QuarantineNoticeProcessManager.PROJECTION_NAME
        )
        if checkpoint is not None and checkpoint.global_position >= nonce:
            break
        await asyncio.sleep(0)
    await coordinator.wait_for_process_managers()


def _cancelled_with_work() -> EventEnvelope:
    """A REAL aggregate cancelled mid-phase, then told what its save landed."""
    aggregate = WorkflowExecutionAggregate()
    aggregate.start_execution(
        StartExecutionCommand(
            execution_id="exec-q1",
            workflow_id="wf-1",
            workflow_name="Quarantine on cancel",
            total_phases=1,
            inputs={},
            phase_definitions=[PhaseDefinition(phase_id="implement", name="Implement", order=1)],
        )
    )
    aggregate.cancel_execution(
        CancelExecutionCommand(execution_id="exec-q1", phase_id="implement", reason="stop")
    )
    aggregate.mark_events_as_committed()
    aggregate.record_cancelled_work(
        RecordCancelledWorkCommand(
            execution_id="exec-q1",
            phase_id="implement",
            quarantined=(
                QuarantinedRef(
                    repository="acme/widget",
                    branch="feat/thing",
                    ref=REF,
                    commit=SHA,
                    commit_count=1,
                    pull_request=42,
                ),
            ),
        )
    )
    (envelope,) = aggregate.get_uncommitted_events()
    assert envelope.event.event_type == "CancelledWorkQuarantined"
    return EventEnvelope(
        event=envelope.event,
        metadata=envelope.metadata.model_copy(
            update={"global_nonce": 7, "event_type": envelope.event.event_type}
        ),
    )


@pytest.mark.asyncio
async def test_a_cancelled_execution_that_landed_a_ref_tells_its_pr_once() -> None:
    manager, commenter = _manager()
    envelope = _cancelled_with_work()
    assert "CancelledWorkQuarantined" in (manager.get_subscribed_event_types() or set())
    await manager.handle_event(envelope, MemoryCheckpointStore())
    assert await manager.process_pending() == 1
    await manager.handle_event(envelope, MemoryCheckpointStore())
    assert await manager.process_pending() == 0
    assert commenter.posts == 1 and commenter.edits == 0
    (body,) = commenter.comments.values()
    assert REF in body and SHA in body and "`implement`" in body


def test_a_cancelled_execution_whose_save_landed_nothing_records_nothing() -> None:
    aggregate = WorkflowExecutionAggregate()
    aggregate.start_execution(
        StartExecutionCommand(
            execution_id="exec-q2",
            workflow_id="wf-1",
            workflow_name="n",
            total_phases=1,
            inputs={},
            phase_definitions=[PhaseDefinition(phase_id="implement", name="I", order=1)],
        )
    )
    with pytest.raises(ValueError, match="Cannot record cancelled work"):
        aggregate.record_cancelled_work(RecordCancelledWorkCommand("exec-q2", "implement", ()))
    aggregate.cancel_execution(CancelExecutionCommand(execution_id="exec-q2", phase_id="implement"))
    aggregate.mark_events_as_committed()
    aggregate.record_cancelled_work(RecordCancelledWorkCommand("exec-q2", "implement", ()))
    assert aggregate.get_uncommitted_events() == []


class _Stream:
    """The execution's stream, written to the live store, refusing its first ``rejections`` saves.

    A rejected save writes nothing, as `ExecutionJournal.append`'s contract
    says; `get_by_id` rebuilds from what was actually written, as a real
    repository does.
    """

    def __init__(self, store: _LiveStore, *, rejections: int = 0) -> None:
        self._store = store
        self.rejections = rejections
        self.history: list[EventEnvelope] = []

    async def save(self, aggregate: WorkflowExecutionAggregate) -> None:
        if self.rejections:
            self.rejections -= 1
            raise RuntimeError("wrong expected version")
        for envelope in aggregate.get_uncommitted_events():
            self.history.append(envelope)
            self._store.publish(envelope.event, envelope.event.event_type)
        aggregate.mark_events_as_committed()

    async def save_new(self, aggregate: WorkflowExecutionAggregate) -> None:
        await self.save(aggregate)

    async def get_by_id(self, aggregate_id: str) -> WorkflowExecutionAggregate | None:
        aggregate = WorkflowExecutionAggregate()
        aggregate.rehydrate(self.history)
        return aggregate

    def recorded(self, event_type: str) -> int:
        return sum(1 for e in self.history if e.event.event_type == event_type)


async def _a_cancelled_run(stream: _Stream) -> tuple[WorkflowExecutionAggregate, ExecutionJournal]:
    """Started and cancelled through the real journal, so both are on the stream."""
    journal = ExecutionJournal(stream, object())  # type: ignore[arg-type]
    aggregate = WorkflowExecutionAggregate()
    aggregate.start_execution(
        StartExecutionCommand(
            execution_id="exec-q1",
            workflow_id="wf-1",
            workflow_name="Quarantine on cancel",
            total_phases=1,
            inputs={},
            phase_definitions=[PhaseDefinition(phase_id="implement", name="Implement", order=1)],
        )
    )
    await journal.open(aggregate)
    aggregate.cancel_execution(
        CancelExecutionCommand(execution_id="exec-q1", phase_id="implement", reason="stop")
    )
    await journal.append(aggregate)
    return aggregate, journal


_LANDED = RecordCancelledWorkCommand(
    execution_id="exec-q1",
    phase_id="implement",
    quarantined=(
        QuarantinedRef(
            repository="acme/widget",
            branch="feat/thing",
            ref=REF,
            commit=SHA,
            commit_count=1,
            pull_request=42,
        ),
    ),
)


@pytest.mark.asyncio
async def test_a_cancelled_run_whose_append_is_rejected_still_tells_its_pr_once() -> None:
    """Aggregate -> journal -> stored event -> coordinator -> one post, and none on replay.

    The first append of the landed refs is REJECTED, as a version conflict
    would be. The fact must still reach the stream exactly once, and the PR
    hear of it from the stored event alone - nothing here calls
    `process_pending()`.
    """
    manager, commenter = _manager()
    store = _LiveStore()
    checkpoints = MemoryCheckpointStore()
    coordinator = SubscriptionCoordinator(
        event_store=store, checkpoint_store=checkpoints, projections=[manager]
    )
    runner = asyncio.create_task(coordinator.start())
    try:
        await asyncio.wait_for(store.subscribed.wait(), 5)
        stream = _Stream(store)
        aggregate, journal = await _a_cancelled_run(stream)
        stream.rejections = 1

        await CancelledWorkLedger(journal, InMemoryProjectionStore()).record(aggregate, _LANDED)

        assert stream.rejections == 0, "the rejection was never exercised"
        assert stream.recorded("CancelledWorkQuarantined") == 1
        await asyncio.wait_for(_settled(coordinator, checkpoints, len(stream.history)), 5)
        assert commenter.posts == 1
        (body,) = commenter.comments.values()
        assert REF in body and SHA in body
    finally:
        await coordinator.stop()
        runner.cancel()
        await asyncio.gather(runner, return_exceptions=True)

    # A restart: the whole stream again, from a checkpoint that has none of it.
    replay = SubscriptionCoordinator(
        event_store=store, checkpoint_store=MemoryCheckpointStore(), projections=[manager]
    )
    runner = asyncio.create_task(replay.start())
    try:
        await asyncio.wait_for(store.subscribed.wait(), 5)
        await replay.wait_for_process_managers()
        assert commenter.posts == 1 and commenter.edits == 0
    finally:
        await replay.stop()
        runner.cancel()
        await asyncio.gather(runner, return_exceptions=True)


@pytest.mark.asyncio
async def test_refs_the_store_refuses_to_the_retry_limit_are_owed_until_it_takes_them(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Rejected through the limit, then a restart against a store that recovered.

    Owed survives the restart because it is in the durable store, not in the
    ledger: the second ledger and journal share nothing with the first but
    that store and the stream. One fact lands, and the PR hears of it from the
    stored event alone, once, and not again on replay.
    """
    monkeypatch.setattr(cancelled_work_record, "_ATTEMPTS", 2)
    manager, commenter = _manager()
    store = _LiveStore()
    checkpoints = MemoryCheckpointStore()
    coordinator = SubscriptionCoordinator(
        event_store=store, checkpoint_store=checkpoints, projections=[manager]
    )
    runner = asyncio.create_task(coordinator.start())
    try:
        await asyncio.wait_for(store.subscribed.wait(), 5)
        stream = _Stream(store)
        owed = InMemoryProjectionStore()
        aggregate, journal = await _a_cancelled_run(stream)
        stream.rejections = 2

        await CancelledWorkLedger(journal, owed).record(aggregate, _LANDED)

        assert stream.rejections == 0, "the retry limit was never reached"
        assert stream.recorded("CancelledWorkQuarantined") == 0
        assert len(await owed.get_all(OWED_CANCELLED_WORK)) == 1

        # Still refusing: settling keeps it owed rather than dropping it.
        stream.rejections = 2
        restarted = CancelledWorkLedger(ExecutionJournal(stream, object()), owed)  # type: ignore[arg-type]
        assert await restarted.settle() == 0
        assert len(await owed.get_all(OWED_CANCELLED_WORK)) == 1

        # The store recovers; the next run's settle appends it, once.
        stream.rejections = 0
        assert await restarted.settle() == 1
        assert await restarted.settle() == 0
        assert await owed.get_all(OWED_CANCELLED_WORK) == []
        assert stream.recorded("CancelledWorkQuarantined") == 1

        await asyncio.wait_for(_settled(coordinator, checkpoints, len(stream.history)), 5)
        assert commenter.posts == 1
        (body,) = commenter.comments.values()
        assert REF in body and SHA in body
    finally:
        await coordinator.stop()
        runner.cancel()
        await asyncio.gather(runner, return_exceptions=True)
    await _replay_posts_nothing(store, manager, commenter)


async def _replay_posts_nothing(
    store: _LiveStore, manager: QuarantineNoticeProcessManager, commenter: _Commenter
) -> None:
    """A restart: the whole stream again, from a checkpoint that has none of it."""
    replay = SubscriptionCoordinator(
        event_store=store, checkpoint_store=MemoryCheckpointStore(), projections=[manager]
    )
    runner = asyncio.create_task(replay.start())
    try:
        await asyncio.wait_for(store.subscribed.wait(), 5)
        await replay.wait_for_process_managers()
        assert commenter.posts == 1 and commenter.edits == 0
    finally:
        await replay.stop()
        runner.cancel()
        await asyncio.gather(runner, return_exceptions=True)
