"""The #1545 detector, driven through the real execution projections.

The store holds two executions. One projects normally. For the other the
projections never see WorkflowExecutionStarted (what the commit-order gap
fixed in event-sourcing-platform#337 did to exec-db527ea0d361) but do see the later WorkflowFailed,
whose #598 fallback writes a row with no start. Both checkpoints end at the
head, so lag says nothing is wrong. The detector must name the dropped one.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from event_sourcing.core.event import EventEnvelope, EventMetadata
from event_sourcing.stores.memory_checkpoint import MemoryCheckpointStore

from syn_adapters.projection_stores import InMemoryProjectionStore
from syn_adapters.subscriptions.unapplied_starts import (
    UnappliedStart,
    UnappliedStartDetector,
    UnappliedStartWatch,
)
from syn_domain.contexts.orchestration.domain.events.WorkflowExecutionStartedEvent import (
    WorkflowExecutionStartedEvent,
)
from syn_domain.contexts.orchestration.domain.events.WorkflowFailedEvent import WorkflowFailedEvent
from syn_domain.contexts.orchestration.slices.get_execution_detail.projection import (
    WorkflowExecutionDetailProjection,
)
from syn_domain.contexts.orchestration.slices.list_executions.projection import (
    WorkflowExecutionListProjection,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from event_sourcing import AutoDispatchProjection
    from event_sourcing.core.event import DomainEvent

pytestmark = pytest.mark.unit

_AT = datetime(2026, 10, 3, 22, 17, 24, tzinfo=UTC)
FINE = "exec-62d51fee08b1"
DROPPED = "exec-db527ea0d361"


def _started(execution_id: str) -> WorkflowExecutionStartedEvent:
    return WorkflowExecutionStartedEvent(
        workflow_id="dreamship-implement-v5",
        execution_id=execution_id,
        workflow_name="dreamship-implement-v5",
        started_at=_AT,
        total_phases=3,
        inputs={},
    )


def _failed(execution_id: str) -> WorkflowFailedEvent:
    return WorkflowFailedEvent(
        workflow_id="dreamship-implement-v5",
        execution_id=execution_id,
        failed_at=_AT,
        failed_phase_id="implement",
        error_message="phase failed",
        completed_phases=0,
        total_phases=3,
    )


def _envelope(
    event: DomainEvent, global_nonce: int, execution_id: str
) -> EventEnvelope[DomainEvent]:
    return EventEnvelope(
        event=event,
        metadata=EventMetadata(
            aggregate_nonce=1,
            aggregate_id=f"WorkflowExecution-{execution_id}",
            aggregate_type="WorkflowExecution",
            global_nonce=global_nonce,
            event_type=event.event_type,
        ),
    )


STORE = (
    _envelope(_started(FINE), 39_490, FINE),
    _envelope(_started(DROPPED), 39_502, DROPPED),
    _envelope(_failed(DROPPED), 41_000, DROPPED),
)


class _ListStore:
    """`read_all` over a fixed list, with the client's inclusive-from paging."""

    def __init__(self, events: tuple[EventEnvelope[DomainEvent], ...]) -> None:
        self._events = events

    async def read_all(
        self, from_global_nonce: int = 0, max_count: int = 100, forward: bool = True
    ) -> tuple[list[EventEnvelope[DomainEvent]], bool, int]:
        assert forward
        after = [e for e in self._events if (e.metadata.global_nonce or 0) >= from_global_nonce]
        page = after[:max_count]
        is_end = len(after) <= max_count
        next_from = (page[-1].metadata.global_nonce or 0) + 1 if page else from_global_nonce
        return page, is_end, next_from


async def _project(
    projections: list[AutoDispatchProjection],
    checkpoints: MemoryCheckpointStore,
    *,
    drop: int | None,
) -> None:
    """Hand every stored event to each projection the way the coordinator does, except `drop`."""
    for envelope in STORE:
        if envelope.metadata.global_nonce == drop:
            continue
        for projection in projections:
            await projection.handle_event(envelope, checkpoints)


async def _setup(
    *, drop: int | None
) -> tuple[
    UnappliedStartDetector,
    WorkflowExecutionListProjection,
    WorkflowExecutionDetailProjection,
    MemoryCheckpointStore,
]:
    checkpoints = MemoryCheckpointStore()
    listing = WorkflowExecutionListProjection(InMemoryProjectionStore())
    detail = WorkflowExecutionDetailProjection(InMemoryProjectionStore())
    await _project([listing, detail], checkpoints, drop=drop)
    detector = UnappliedStartDetector(
        _ListStore(STORE),  # type: ignore[arg-type]
        checkpoints,
        [listing, detail],
    )
    return detector, listing, detail, checkpoints


@pytest.mark.asyncio
async def test_a_start_skipped_below_the_checkpoint_is_reported_for_both_read_models() -> None:
    detector, _, _, checkpoints = await _setup(drop=39_502)
    # The silent part: both checkpoints are at the head.
    for name in ("workflow_executions", "workflow_execution_details"):
        checkpoint = await checkpoints.get_checkpoint(name)
        assert checkpoint is not None and checkpoint.global_position == 41_000

    report = await detector.check()

    assert report.unapplied == (
        UnappliedStart(
            projection="workflow_execution_details", execution_id=DROPPED, global_nonce=39_502
        ),
        UnappliedStart(projection="workflow_executions", execution_id=DROPPED, global_nonce=39_502),
    )
    assert report.scanned_through == 41_000


@pytest.mark.asyncio
async def test_nothing_is_reported_when_every_start_was_applied() -> None:
    detector, _, _, _ = await _setup(drop=None)

    assert (await detector.check()).unapplied == ()


@pytest.mark.asyncio
async def test_a_start_above_the_checkpoint_is_lag_not_a_drop() -> None:
    checkpoints = MemoryCheckpointStore()
    listing = WorkflowExecutionListProjection(InMemoryProjectionStore())
    await listing.handle_event(STORE[0], checkpoints)  # stops at 39_490
    detector = UnappliedStartDetector(_ListStore(STORE), checkpoints, [listing])  # type: ignore[arg-type]

    assert (await detector.check()).unapplied == ()


@pytest.mark.asyncio
async def test_a_repaired_row_clears_on_the_next_check() -> None:
    detector, listing, detail, checkpoints = await _setup(drop=39_502)
    assert (await detector.check()).unapplied

    # What the runbook's rebuild does: replay the stream into empty read models.
    await listing.clear_all_data()
    await detail.clear_all_data()
    await _project([listing, detail], checkpoints, drop=None)

    assert (await detector.check()).unapplied == ()


@pytest.mark.asyncio
async def test_a_start_that_commits_below_an_earlier_scan_is_still_reported() -> None:
    """#1545's own mechanism, aimed at the detector: the start becomes visible
    in the store only after a check has already read past its nonce. A cursor
    would never look back; a full reconciliation does."""
    checkpoints = MemoryCheckpointStore()
    listing = WorkflowExecutionListProjection(InMemoryProjectionStore())
    await _project([listing], checkpoints, drop=39_502)
    store = _ListStore((STORE[0], STORE[2]))  # 39_502 not committed yet
    detector = UnappliedStartDetector(store, checkpoints, [listing])  # type: ignore[arg-type]
    assert (await detector.check()).unapplied == ()

    store._events = STORE  # the late commit lands below what was already read

    assert {u.execution_id for u in (await detector.check()).unapplied} == {DROPPED}


@pytest.mark.asyncio
async def test_a_row_lost_after_a_clean_check_is_reported() -> None:
    detector, listing, _, _ = await _setup(drop=None)
    assert (await detector.check()).unapplied == ()

    await listing.clear_all_data()  # a botched rebuild, a truncation

    lost = (await detector.check()).unapplied
    assert {(u.projection, u.execution_id) for u in lost} == {
        ("workflow_executions", FINE),
        ("workflow_executions", DROPPED),
    }


@pytest.mark.asyncio
async def test_the_watch_publishes_a_report_and_health_never_waits_for_a_scan() -> None:
    detector, _, _, _ = await _setup(drop=39_502)
    watch = UnappliedStartWatch(detector, interval_seconds=3_600)
    assert watch.latest is None  # not measured yet, which is not "healthy"

    watch.start()
    try:
        for _ in range(100):
            if watch.latest is not None:
                break
            await asyncio.sleep(0.01)
    finally:
        await watch.stop()

    assert watch.latest is not None
    assert {u.execution_id for u in watch.latest.unapplied} == {DROPPED}


class _ParkedListStore(_ListStore):
    """`_ListStore` that the real coordinator can start against: a backward
    `read_all` for its head snapshot, and a live stream that never yields."""

    def __init__(self, events: tuple[EventEnvelope[DomainEvent], ...]) -> None:
        super().__init__(events)
        self.parked = asyncio.Event()

    async def read_all(
        self, from_global_nonce: int = 0, max_count: int = 100, forward: bool = True
    ) -> tuple[list[EventEnvelope[DomainEvent]], bool, int]:
        if not forward:
            last = self._events[-1]
            return [last], True, last.metadata.global_nonce or 0
        return await super().read_all(from_global_nonce, max_count, forward)

    async def subscribe(self, from_global_nonce: int) -> AsyncIterator[EventEnvelope[DomainEvent]]:
        await self.parked.wait()
        return
        yield  # pragma: no cover - unreachable, makes this an async generator


@pytest.mark.asyncio
async def test_the_real_coordinator_service_runs_the_watch_and_publishes_the_drop() -> None:
    """Wiring, not logic: deleting the watch from `start()` must fail a test."""
    from syn_adapters.subscriptions.coordinator_service import CoordinatorSubscriptionService

    checkpoints = MemoryCheckpointStore()
    listing = WorkflowExecutionListProjection(InMemoryProjectionStore())
    detail = WorkflowExecutionDetailProjection(InMemoryProjectionStore())
    await _project([listing, detail], checkpoints, drop=39_502)
    store = _ParkedListStore(STORE)
    service = CoordinatorSubscriptionService(
        event_store=store,  # type: ignore[arg-type]  # double, not EventStoreClient
        projections=[listing, detail],
        checkpoint_store=checkpoints,
    )
    await service.start()
    try:
        report = None
        for _ in range(200):
            report = await service.describe_unapplied_starts()
            if report is not None:
                break
            await asyncio.sleep(0.01)
    finally:
        store.parked.set()
        await service.stop()

    assert report is not None
    assert {(u.projection, u.execution_id) for u in report.unapplied} == {
        ("workflow_executions", DROPPED),
        ("workflow_execution_details", DROPPED),
    }
