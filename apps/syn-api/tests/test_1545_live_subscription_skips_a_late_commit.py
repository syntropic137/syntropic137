"""#1545: a start that commits after a higher nonce never reaches the read models.

This is the PROOF of the mechanism. It drives the REAL ``SubscriptionCoordinator``
and the REAL execution projections from a store double that copies the Rust
store's live loop, then asserts the projection ends up WITHOUT the start.

What is copied, and from where (lib/event-sourcing-platform/event-store/
eventstore-backend-postgres):

- ``migrations/20250827090000_init.sql``: ``global_nonce BIGSERIAL``. A nonce
  is drawn at INSERT and becomes readable at COMMIT, so two concurrent appends
  can commit out of nonce order.
- ``src/store_postgres.rs`` live phase: ``WHERE global_nonce > $cursor`` where
  the cursor is the last nonce YIELDED (``yielded_cursor``). Once N+1 has been
  yielded, N is below the cursor for good.

``appends_commit_in_order`` is the proposed ESP fix
(docs/handoffs/1545-esp-append-commit-order.patch): a per-tenant advisory lock
taken before the nonce is drawn, so append N+1 cannot commit until N has. The
double models its EFFECT, not the SQL; the SQL itself is pinned by the
handoff's ``it_commit_order`` test against real Postgres.

Why the fix has to be ordered COMMITS and not a store that re-delivers late
rows: the coordinator ignores anything at or below a projection's checkpoint
(lib/event-sourcing-platform/event-sourcing/python/src/event_sourcing/
subscriptions/coordinator.py:802), so 39502 delivered after 39503 is dropped
there instead. Checked by mutating this double's live loop to yield every
unyielded nonce: the "without" test still passes.

The detector (test_1545_a_dropped_start_is_reported.py) is separate coverage:
it reports a drop whatever the cause. This file is about the cause.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from event_sourcing import EventEnvelope, EventMetadata
from event_sourcing.stores.memory_checkpoint import MemoryCheckpointStore
from event_sourcing.subscriptions.coordinator import SubscriptionCoordinator

from syn_adapters.projection_stores import InMemoryProjectionStore
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

    from event_sourcing import DomainEvent

pytestmark = pytest.mark.unit

SLOW = "exec-db527ea0d361"  # its append drew 39502 and committed last
FAST = "exec-62d51fee08b1"  # its append drew 39503 and committed first
EARLIER = "exec-0000000000aa"
WORKFLOW_ID = "dreamship-implement-v5"
_AT = datetime(2026, 10, 3, 22, 17, 24, tzinfo=UTC)
_TIMEOUT_S = 5.0


def _started(execution_id: str) -> WorkflowExecutionStartedEvent:
    return WorkflowExecutionStartedEvent(
        workflow_id=WORKFLOW_ID,
        execution_id=execution_id,
        workflow_name="dreamship-implement",
        started_at=_AT,
        total_phases=3,
        inputs={},
    )


def _failed(execution_id: str) -> WorkflowFailedEvent:
    return WorkflowFailedEvent(
        workflow_id=WORKFLOW_ID,
        execution_id=execution_id,
        failed_at=_AT,
        failed_phase_id="implement",
        error_message="agent failed",
        completed_phases=0,
        total_phases=3,
    )


def _envelope(nonce: int, event: DomainEvent) -> EventEnvelope[DomainEvent]:
    return EventEnvelope(
        event=event,
        metadata=EventMetadata(
            aggregate_id=getattr(event, "execution_id", ""),
            aggregate_type="WorkflowExecution",
            aggregate_nonce=1,
            global_nonce=nonce,
            event_type=event.event_type,
        ),
    )


class _SequenceStore:
    """Postgres + the Rust live loop, as far as commit visibility goes."""

    def __init__(self, *, appends_commit_in_order: bool) -> None:
        self._in_order = appends_commit_in_order
        self._drawn: dict[int, EventEnvelope[DomainEvent]] = {}
        self._committed: set[int] = set()
        self._changed = asyncio.Condition()
        self._delivered_through = 0
        self._idle = False
        self.subscribed = asyncio.Event()

    def _visible(self) -> list[int]:
        """Committed nonces a reader can see, ascending."""
        if not self._in_order:
            return sorted(self._committed)
        # The advisory lock: append N+1 waits for N, so nothing above an
        # uncommitted nonce has committed yet.
        visible: list[int] = []
        for nonce in sorted(self._drawn):
            if nonce not in self._committed:
                break
            visible.append(nonce)
        return visible

    def draw(self, nonce: int, event: DomainEvent) -> None:
        """INSERT: the BIGSERIAL hands out `nonce`; nothing is readable yet."""
        self._drawn[nonce] = _envelope(nonce, event)

    async def commit(self, nonce: int) -> None:
        self._committed.add(nonce)
        async with self._changed:
            self._changed.notify_all()

    async def append(self, nonce: int, event: DomainEvent) -> None:
        self.draw(nonce, event)
        await self.commit(nonce)

    async def wait_delivered_through(self, nonce: int) -> None:
        """Until the live loop has handed out everything visible up to `nonce`."""

        async def reached() -> None:
            async with self._changed:
                await self._changed.wait_for(lambda: self._delivered_through >= nonce)

        await asyncio.wait_for(reached(), timeout=_TIMEOUT_S)

    async def wait_idle(self) -> None:
        """Until the live loop has yielded everything visible and is polling again."""

        def idle() -> bool:
            visible = self._visible()
            return self._idle and self._delivered_through >= (visible[-1] if visible else 0)

        async def reached() -> None:
            async with self._changed:
                await self._changed.wait_for(idle)

        await asyncio.wait_for(reached(), timeout=_TIMEOUT_S)

    async def subscribe(self, from_global_nonce: int) -> AsyncIterator[EventEnvelope[DomainEvent]]:
        # Replay phase reads `global_nonce >= from`; the live phase then polls
        # `global_nonce > cursor`, cursor = last yielded. One rule covers both.
        cursor = from_global_nonce - 1
        self.subscribed.set()
        while True:
            for nonce in [n for n in self._visible() if n > cursor]:
                yield self._drawn[nonce]
                cursor = nonce
            async with self._changed:
                self._delivered_through = max(self._delivered_through, cursor)
                self._idle = True
                self._changed.notify_all()
                await self._changed.wait_for(lambda: any(n > cursor for n in self._visible()))
                self._idle = False

    async def read_all(
        self, from_global_nonce: int = 0, max_count: int = 100, forward: bool = True
    ) -> tuple[list[EventEnvelope[DomainEvent]], bool, int]:
        visible = self._visible()
        if not forward:
            page = [n for n in reversed(visible) if n <= from_global_nonce][:max_count]
            return [self._drawn[n] for n in page], True, 0
        page = [n for n in visible if n >= from_global_nonce][:max_count]
        nxt = page[-1] + 1 if page else from_global_nonce
        return [self._drawn[n] for n in page], len(page) < max_count, nxt


async def _run_incident(
    *, appends_commit_in_order: bool
) -> tuple[WorkflowExecutionListProjection, WorkflowExecutionDetailProjection]:
    """Two concurrent starts, the lower nonce committing second, then terminals."""
    store = _SequenceStore(appends_commit_in_order=appends_commit_in_order)
    await store.append(39490, _started(EARLIER))  # history, so the coordinator goes live

    projection_store = InMemoryProjectionStore()
    listing = WorkflowExecutionListProjection(projection_store)
    detail = WorkflowExecutionDetailProjection(projection_store)
    coordinator = SubscriptionCoordinator(
        event_store=store,
        checkpoint_store=MemoryCheckpointStore(),
        projections=[listing, detail],
    )
    runner = asyncio.create_task(coordinator.start())
    try:
        await asyncio.wait_for(store.subscribed.wait(), timeout=_TIMEOUT_S)
        await store.wait_delivered_through(39490)

        store.draw(39502, _started(SLOW))  # slow transaction: drawn, not committed
        store.draw(39503, _started(FAST))
        await store.commit(39503)  # the fast one commits first
        # The live loop polls in between - with ordered commits there is nothing
        # new for it to see, without them it yields 39503 and moves past 39502.
        await store.wait_idle()
        await store.commit(39502)  # the slow one commits

        await store.append(39519, _failed(SLOW))
        await store.wait_delivered_through(39519)
        # Delivered is not yet applied: wait for both projections' checkpoints.
        await asyncio.wait_for(_checkpointed(coordinator, 39519), timeout=_TIMEOUT_S)
    finally:
        await coordinator.stop()
        runner.cancel()
        await asyncio.gather(runner, return_exceptions=True)
    return listing, detail


async def _checkpointed(coordinator: SubscriptionCoordinator, nonce: int) -> None:
    store = coordinator._checkpoint_store
    names = (
        WorkflowExecutionListProjection.PROJECTION_NAME,
        WorkflowExecutionDetailProjection.PROJECTION_NAME,
    )
    while True:
        positions = [await store.get_checkpoint(name) for name in names]
        if all(p is not None and p.global_position >= nonce for p in positions):
            return
        await asyncio.sleep(0.01)


class TestALateCommitIsSkippedByTheLiveSubscription:
    @pytest.mark.asyncio
    async def test_without_ordered_commits_the_start_never_reaches_the_read_models(self) -> None:
        listing, detail = await _run_incident(appends_commit_in_order=False)

        # The faster start is there: delivery worked for everything it saw.
        assert (await detail.get_by_id(FAST)) is not None
        # The slow start committed and is in the store, yet was never applied.
        # The terminal handler upserted a row without a start: #1545's row.
        row = await detail.get_by_id(SLOW)
        assert row is not None and row.started_at is None, (
            f"{SLOW}'s start committed after 39503 was delivered; the live loop's "
            "`global_nonce > cursor` must have skipped it"
        )
        summary = await listing.get_by_id(SLOW)
        assert summary is None or summary.started_at is None

    @pytest.mark.asyncio
    async def test_with_ordered_commits_every_start_is_applied(self) -> None:
        listing, detail = await _run_incident(appends_commit_in_order=True)

        for execution_id in (EARLIER, SLOW, FAST):
            row = await detail.get_by_id(execution_id)
            assert row is not None and row.started_at is not None, execution_id
            summary = await listing.get_by_id(execution_id)
            assert summary is not None and summary.started_at is not None, execution_id
