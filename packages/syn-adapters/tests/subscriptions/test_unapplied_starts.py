"""The #1545 detector, driven through the real execution projections.

The store holds two executions. One projects normally. For the other the
projections never see WorkflowExecutionStarted (what the commit-order gap in
ESP ADR-026 did to exec-db527ea0d361) but do see the later WorkflowFailed,
whose #598 fallback writes a row with no start. Both checkpoints end at the
head, so lag says nothing is wrong. The detector must name the dropped one.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from event_sourcing.core.event import EventEnvelope, EventMetadata
from event_sourcing.stores.memory_checkpoint import MemoryCheckpointStore

from syn_adapters.projection_stores import InMemoryProjectionStore
from syn_adapters.subscriptions.unapplied_starts import (
    UnappliedStart,
    UnappliedStartDetector,
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
    from event_sourcing import AutoDispatchProjection
    from event_sourcing.core.event import DomainEvent

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
    *, drop: int | None, page: int = 5_000
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
        max_events_per_check=page,
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
async def test_a_bounded_scan_converges_over_several_checks() -> None:
    detector, _, _, _ = await _setup(drop=39_502, page=1)

    first = await detector.check()
    assert first.scanned_through == 39_490 and first.unapplied == ()
    await detector.check()
    third = await detector.check()

    assert {u.execution_id for u in third.unapplied} == {DROPPED}


@pytest.mark.asyncio
async def test_a_repaired_row_clears_on_the_next_check() -> None:
    detector, listing, detail, checkpoints = await _setup(drop=39_502)
    assert (await detector.check()).unapplied

    # What the runbook's rebuild does: replay the stream into empty read models.
    await listing.clear_all_data()
    await detail.clear_all_data()
    await _project([listing, detail], checkpoints, drop=None)

    assert (await detector.check()).unapplied == ()
