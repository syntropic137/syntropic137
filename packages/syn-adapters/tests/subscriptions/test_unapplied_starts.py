"""The #1545 detector, driven through the real execution projections.

The store holds two executions. One projects normally. For the other the
projections never see WorkflowExecutionStarted (what the commit-order gap
fixed in event-sourcing-platform#337 did to exec-db527ea0d361) but do see the
later WorkflowFailed, whose #598 fallback writes a row with no start. Both
checkpoints end at the head, so lag says nothing is wrong. The detector must
name the dropped one, and only the dropped one, without ever mistaking a
rebuild in progress for a drop.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import grpc
import pytest
from event_sourcing.core.errors import EventStoreError
from event_sourcing.core.event import EventEnvelope, EventMetadata
from event_sourcing.stores.memory_checkpoint import MemoryCheckpointStore

from syn_adapters.projection_stores import InMemoryProjectionStore
from syn_adapters.subscriptions.paged_read import OversizedEventError
from syn_adapters.subscriptions import unapplied_starts
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
    from collections.abc import AsyncIterator, Sequence

    from event_sourcing import AutoDispatchProjection
    from event_sourcing.core.event import DomainEvent

    from syn_domain.pagination import ProjectionRecord

pytestmark = pytest.mark.unit

_AT = datetime(2026, 10, 3, 22, 17, 24, tzinfo=UTC)
FINE = "exec-62d51fee08b1"
DROPPED = "exec-db527ea0d361"
LIST = "workflow_executions"
DETAIL = "workflow_execution_details"


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
    """`read_all` over a list, with the client's inclusive-from paging."""

    def __init__(self, events: Sequence[EventEnvelope[DomainEvent]]) -> None:
        self.events = list(events)
        self.events_read = 0

    async def read_all(
        self, from_global_nonce: int = 0, max_count: int = 100, forward: bool = True
    ) -> tuple[list[EventEnvelope[DomainEvent]], bool, int]:
        if not forward:
            last = self.events[-1]
            return [last], True, last.metadata.global_nonce or 0
        ordered = sorted(self.events, key=lambda e: e.metadata.global_nonce or 0)
        after = [e for e in ordered if (e.metadata.global_nonce or 0) >= from_global_nonce]
        page = after[:max_count]
        self.events_read += len(page)
        is_end = len(after) <= max_count
        next_from = (page[-1].metadata.global_nonce or 0) + 1 if page else from_global_nonce
        return page, is_end, next_from


class _Spy:
    """Counts every read-model query the detector makes, and the ids it asks about."""

    def __init__(self, inner: WorkflowExecutionListProjection | WorkflowExecutionDetailProjection):
        self.inner = inner
        self.queries = 0
        self.ids_asked: list[str] = []

    def get_name(self) -> str:
        return self.inner.get_name()

    async def applied_starts(self, execution_ids: Sequence[str]) -> set[str]:
        self.queries += 1
        self.ids_asked.extend(execution_ids)
        return await self.inner.applied_starts(execution_ids)


async def _settled() -> bool:
    return True


async def _project(
    projections: Sequence[AutoDispatchProjection],
    checkpoints: MemoryCheckpointStore,
    events: Sequence[EventEnvelope[DomainEvent]] = STORE,
    *,
    drop: int | None,
) -> None:
    """Hand events to each projection the way the coordinator does, except `drop`."""
    for envelope in events:
        if envelope.metadata.global_nonce == drop:
            continue
        for projection in projections:
            await projection.handle_event(envelope, checkpoints)


class _Rig:
    def __init__(
        self, *, drop: int | None, max_events: int = 20_000, safety_window: int = 1_000
    ) -> None:
        self.checkpoints = MemoryCheckpointStore()
        self.listing = WorkflowExecutionListProjection(InMemoryProjectionStore())
        self.detail = WorkflowExecutionDetailProjection(InMemoryProjectionStore())
        self.store = _ListStore(STORE)
        self.spies = (_Spy(self.listing), _Spy(self.detail))
        self.drop = drop
        self.max_events = max_events
        self.safety_window = safety_window
        self.settled = True

    async def is_settled(self) -> bool:
        return self.settled

    def detector(self) -> UnappliedStartDetector:
        return UnappliedStartDetector(
            self.store,
            self.checkpoints,
            self.spies,
            is_settled=self.is_settled,
            max_events_per_check=self.max_events,
            safety_window=self.safety_window,
        )

    async def project(self) -> None:
        await _project([self.listing, self.detail], self.checkpoints, drop=self.drop)

    @property
    def queries(self) -> int:
        return sum(s.queries for s in self.spies)


async def _rig(*, drop: int | None, max_events: int = 20_000, safety_window: int = 1_000) -> _Rig:
    rig = _Rig(drop=drop, max_events=max_events, safety_window=safety_window)
    await rig.project()
    return rig


def _pairs(report: unapplied_starts.UnappliedStartsReport | None) -> set[tuple[str, str]]:
    assert report is not None
    return {(u.projection, u.execution_id) for u in report.unapplied}


@pytest.mark.asyncio
async def test_a_start_skipped_below_the_checkpoint_is_reported_once_confirmed() -> None:
    rig = await _rig(drop=39_502)
    for name in (LIST, DETAIL):  # the silent part: both checkpoints are at the head
        checkpoint = await rig.checkpoints.get_checkpoint(name)
        assert checkpoint is not None and checkpoint.global_position == 41_000
    detector = rig.detector()

    first = await detector.check()
    assert first is not None and first.unapplied == ()  # one sighting is not a finding
    second = await detector.check()

    assert second is not None
    assert second.unapplied == (
        UnappliedStart(projection=DETAIL, execution_id=DROPPED, global_nonce=39_502),
        UnappliedStart(projection=LIST, execution_id=DROPPED, global_nonce=39_502),
    )
    assert second.scanned_through == 41_000


@pytest.mark.asyncio
async def test_nothing_is_reported_when_every_start_was_applied() -> None:
    detector = (await _rig(drop=None)).detector()
    await detector.check()

    assert _pairs(await detector.check()) == set()


@pytest.mark.asyncio
async def test_a_start_above_the_lowest_checkpoint_is_lag_not_a_drop() -> None:
    rig = _Rig(drop=None)
    await _project([rig.listing, rig.detail], rig.checkpoints, STORE[:1], drop=None)
    await _project([rig.listing], rig.checkpoints, STORE[1:], drop=39_502)  # detail at 39_490
    detector = rig.detector()
    await detector.check()

    assert _pairs(await detector.check()) == set()


@pytest.mark.asyncio
async def test_a_second_check_with_no_new_events_makes_no_lookups() -> None:
    # A window wide enough that both starts are re-read: only the confirmed set
    # keeps them from being looked up again.
    rig = await _rig(drop=None, safety_window=5_000)
    detector = rig.detector()
    await detector.check()
    after_first = rig.queries
    assert after_first == 2  # one batched query per read model, not one per start

    await detector.check()

    assert rig.queries == after_first


@pytest.mark.asyncio
async def test_a_start_newer_than_the_mark_is_still_caught_and_only_it_is_looked_up() -> None:
    rig = await _rig(drop=None)
    detector = rig.detector()
    await detector.check()
    late = "exec-new"
    newer = _envelope(_started(late), 42_000, late)
    rig.store.events.append(newer)
    # The projections pass it without applying it: checkpoints move, rows do not.
    for name in (LIST, DETAIL):
        checkpoint = await rig.checkpoints.get_checkpoint(name)
        assert checkpoint is not None
        await rig.checkpoints.save_checkpoint(checkpoint.advance_to(42_000))
    for spy in rig.spies:
        spy.ids_asked.clear()

    await detector.check()
    report = await detector.check()

    assert _pairs(report) == {(LIST, late), (DETAIL, late)}
    assert {i for spy in rig.spies for i in spy.ids_asked} == {late}


@pytest.mark.asyncio
async def test_lookups_are_batched(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(unapplied_starts, "LOOKUP_BATCH_SIZE", 1)
    rig = await _rig(drop=None)

    await rig.detector().check()

    assert [s.queries for s in rig.spies] == [2, 2]  # two starts, batches of one


@pytest.mark.asyncio
async def test_a_bounded_check_converges_over_several_checks() -> None:
    rig = await _rig(drop=39_502, max_events=1)
    detector = rig.detector()

    first = await detector.check()
    assert first is not None and first.scanned_through == 39_490
    for _ in range(3):
        report = await detector.check()

    assert _pairs(report) == {(LIST, DROPPED), (DETAIL, DROPPED)}


@pytest.mark.asyncio
async def test_a_start_that_commits_below_the_mark_inside_the_window_is_caught() -> None:
    """#1545's mechanism aimed at the detector: the start becomes visible in the
    store after a check has already moved its mark past that nonce."""
    # 39_502 sits 1_498 below the head, so the window must reach that far.
    rig = await _rig(drop=39_502, safety_window=2_000)
    rig.store.events = [STORE[0], STORE[2]]  # 39_502 not committed yet
    detector = rig.detector()
    await detector.check()
    assert detector._mark == 41_000

    rig.store.events = list(STORE)  # the late commit lands below the mark
    await detector.check()
    report = await detector.check()

    assert _pairs(report) == {(LIST, DROPPED), (DETAIL, DROPPED)}


@pytest.mark.asyncio
async def test_nothing_is_judged_while_the_read_path_is_catching_up() -> None:
    rig = await _rig(drop=39_502)
    rig.settled = False
    detector = rig.detector()

    assert await detector.check() is None
    assert rig.queries == 0


@pytest.mark.asyncio
async def test_a_rebuild_between_checkpoint_capture_and_row_check_reports_nothing() -> None:
    """The interleaving itself: checkpoints are captured at the head, then a
    version rebuild clears the rows and deletes the checkpoint, then the rows
    are read and every start is missing for a healthy reason."""
    rig = await _rig(drop=None)
    detector = rig.detector()
    rebuilt = False

    async def rebuild_before_answering(execution_ids: Sequence[str]) -> set[str]:
        nonlocal rebuilt
        if not rebuilt:
            rebuilt = True
            for projection in (rig.listing, rig.detail):
                await projection.clear_all_data()
                await rig.checkpoints.delete_checkpoint(projection.get_name())
        return await WorkflowExecutionListProjection.applied_starts(rig.listing, execution_ids)

    rig.spies[0].inner.applied_starts = rebuild_before_answering  # type: ignore[method-assign]

    assert await detector.check() is None
    assert rebuilt

    # The rebuild replays; nothing it passed through is ever reported.
    await rig.project()
    await detector.check()
    assert _pairs(await detector.check()) == set()


@pytest.mark.asyncio
async def test_a_rebuild_that_replays_past_the_capture_mid_check_is_never_published() -> None:
    """The harder interleaving: the rebuild clears and replays all the way back
    past the captured checkpoints before the recheck, so the recheck alone
    cannot see it. The second sighting can: the rows are back."""
    rig = await _rig(drop=None)
    detector = rig.detector()
    rebuilt = False

    async def rebuild_and_replay_mid_check(execution_ids: Sequence[str]) -> set[str]:
        nonlocal rebuilt
        if not rebuilt:
            rebuilt = True
            await rig.listing.clear_all_data()
            await rig.checkpoints.delete_checkpoint(LIST)
            answer = await WorkflowExecutionListProjection.applied_starts(
                rig.listing, execution_ids
            )
            await _project([rig.listing], rig.checkpoints, drop=None)
            return answer
        return await WorkflowExecutionListProjection.applied_starts(rig.listing, execution_ids)

    rig.spies[0].inner.applied_starts = rebuild_and_replay_mid_check  # type: ignore[method-assign]

    first = await detector.check()
    assert first is not None and first.unapplied == ()
    assert _pairs(await detector.check()) == set()


@pytest.mark.asyncio
async def test_a_repaired_row_clears_on_the_next_check() -> None:
    rig = await _rig(drop=39_502)
    detector = rig.detector()
    await detector.check()
    assert _pairs(await detector.check())

    # What the runbook's rebuild does: replay the stream into empty read models.
    await rig.listing.clear_all_data()
    await rig.detail.clear_all_data()
    rig.drop = None
    await rig.project()

    assert _pairs(await detector.check()) == set()


@pytest.mark.asyncio
async def test_the_watch_publishes_a_report_and_health_never_waits_for_a_scan() -> None:
    rig = await _rig(drop=39_502)
    watch = UnappliedStartWatch(rig.detector(), interval_seconds=0.01)
    assert watch.latest is None  # not measured yet, which is not "healthy"

    watch.start()
    try:
        for _ in range(200):
            if watch.latest is not None and watch.latest.unapplied:
                break
            await asyncio.sleep(0.01)
    finally:
        await watch.stop()

    assert watch.latest is not None
    assert {u.execution_id for u in watch.latest.unapplied} == {DROPPED}


@pytest.mark.asyncio
async def test_the_watch_keeps_its_last_report_while_the_read_path_is_moving() -> None:
    rig = await _rig(drop=None)
    watch = UnappliedStartWatch(rig.detector(), interval_seconds=0.01)
    watch.start()
    try:
        for _ in range(200):
            if watch.latest is not None:
                break
            await asyncio.sleep(0.01)
        first = watch.latest
        rig.settled = False
        await asyncio.sleep(0.05)
    finally:
        await watch.stop()

    assert first is not None and watch.latest is first


class _ParkedListStore(_ListStore):
    """A store the real coordinator can start against: its live stream never yields."""

    def __init__(self, events: Sequence[EventEnvelope[DomainEvent]]) -> None:
        super().__init__(events)
        self.parked = asyncio.Event()

    async def subscribe(self, from_global_nonce: int) -> AsyncIterator[EventEnvelope[DomainEvent]]:
        await self.parked.wait()
        return
        yield  # pragma: no cover - unreachable, makes this an async generator


@pytest.mark.asyncio
async def test_the_real_coordinator_service_runs_the_watch() -> None:
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

    # The first check ran: it read the store to the head and saw the drop once.
    assert report is not None
    assert report.scanned_through == 41_000


@pytest.mark.asyncio
async def test_a_late_commit_below_the_window_is_out_of_scope_until_a_restart() -> None:
    """The window is the stated bound: history below it is not re-read. A
    restart's rescan (a fresh detector) is what finds such a start."""
    rig = await _rig(drop=39_502, safety_window=100)
    rig.store.events = [STORE[0], STORE[2]]
    detector = rig.detector()
    await detector.check()

    rig.store.events = list(STORE)
    await detector.check()
    assert _pairs(await detector.check()) == set()

    restarted = rig.detector()
    await restarted.check()
    assert _pairs(await restarted.check()) == {(LIST, DROPPED), (DETAIL, DROPPED)}


class _KeyedStoreSpy(InMemoryProjectionStore):
    """The in-memory store with the Postgres store's `get_many`, counting both read paths."""

    def __init__(self) -> None:
        super().__init__()
        self.get_many_calls = 0
        self.query_calls = 0

    async def get_many(self, projection: str, keys: Sequence[str]) -> dict[str, ProjectionRecord]:
        self.get_many_calls += 1
        found: dict[str, ProjectionRecord] = {}
        for key in keys:
            document = await self.get(projection, key)
            if document is not None:
                found[key] = document
        return found

    async def query(self, *args: object, **kwargs: object) -> list[ProjectionRecord]:  # type: ignore[override]  # spy
        self.query_calls += 1
        return await super().query(*args, **kwargs)  # type: ignore[arg-type]  # spy pass-through


@pytest.mark.asyncio
async def test_applied_starts_reads_by_primary_key_never_by_json_filter() -> None:
    """The document key is the execution id, so the lookup is `id = ANY(...)` on
    the primary key. A JSON-field filter has no index and scans the table."""
    checkpoints = MemoryCheckpointStore()
    list_store, detail_store = _KeyedStoreSpy(), _KeyedStoreSpy()
    listing = WorkflowExecutionListProjection(list_store)
    detail = WorkflowExecutionDetailProjection(detail_store)
    await _project([listing, detail], checkpoints, drop=39_502)

    for projection in (listing, detail):
        assert await projection.applied_starts([FINE, DROPPED, "exec-absent"]) == {FINE}

    for store in (list_store, detail_store):
        assert store.get_many_calls == 1
        assert store.query_calls == 0


# --- #1640: a page is bounded by the transport in BYTES, not by count -------


def _resource_exhausted(size: int, limit: int) -> EventStoreError:
    """Exactly what `GrpcEventStoreClient.read_all` raises for an oversize reply."""
    cause = grpc.aio.AioRpcError(
        grpc.StatusCode.RESOURCE_EXHAUSTED,
        grpc.aio.Metadata(),
        grpc.aio.Metadata(),
        details=f"Received message larger than max ({size} vs. {limit})",
    )
    wrapped = EventStoreError(f"Failed to read all events: {cause}")
    wrapped.__cause__ = cause  # the client raises it `from` the RpcError
    return wrapped


class _ByteLimitedStore(_ListStore):
    """`read_all` that refuses any page whose payload exceeds `max_bytes`, as the
    gRPC client refuses a ReadAll reply over its receive limit (4 MiB default).

    The count asked for is irrelevant to the transport; only the bytes are."""

    def __init__(self, events: Sequence[EventEnvelope[DomainEvent]], *, max_bytes: int) -> None:
        super().__init__(events)
        self.max_bytes = max_bytes
        self.refused = 0

    async def read_all(
        self, from_global_nonce: int = 0, max_count: int = 100, forward: bool = True
    ) -> tuple[list[EventEnvelope[DomainEvent]], bool, int]:
        page, is_end, next_from = await super().read_all(from_global_nonce, max_count, forward)
        size = sum(len(envelope.model_dump_json()) for envelope in page)
        if size > self.max_bytes:
            self.refused += 1
            raise _resource_exhausted(size, self.max_bytes)
        return page, is_end, next_from


def _fat_started(execution_id: str) -> WorkflowExecutionStartedEvent:
    # ~25 KB per start, the size #1640 measured on the selfhost store.
    return _started(execution_id).model_copy(update={"inputs": {"task": "x" * 25_000}})


_FAT_IDS = [f"exec-{i:012x}" for i in range(60)]
_FAT_STORE = [_envelope(_fat_started(eid), 1_000 + i, eid) for i, eid in enumerate(_FAT_IDS)]
_FAT_DROPPED = _FAT_IDS[47]
#: 500 -> 250 -> ... -> 1: the refusals one scan can pay before giving up on an event.
_PAGE_SIZE_HALVINGS = 8


@pytest.mark.asyncio
async def test_a_page_over_the_transport_byte_limit_is_read_in_smaller_pages() -> None:
    """#1640: 500 events of ~25 KB came to 12.4 MB, over the 4 MiB client
    limit, and the check failed every interval. Here ~4 events fit and the
    first page asked for does not: the check must still read every event and
    find the dropped start, which sits well past the first refused page."""
    checkpoints = MemoryCheckpointStore()
    listing = WorkflowExecutionListProjection(InMemoryProjectionStore())
    detail = WorkflowExecutionDetailProjection(InMemoryProjectionStore())
    dropped_at = 1_000 + _FAT_IDS.index(_FAT_DROPPED)
    await _project([listing, detail], checkpoints, _FAT_STORE, drop=dropped_at)
    store = _ByteLimitedStore(_FAT_STORE, max_bytes=110_000)
    detector = UnappliedStartDetector(
        store, checkpoints, (listing, detail), is_settled=_settled
    )

    await detector.check()
    report = await detector.check()

    assert store.refused > 0  # the hazard was actually exercised
    assert _pairs(report) == {(LIST, _FAT_DROPPED), (DETAIL, _FAT_DROPPED)}
    assert report is not None and report.scanned_through == _FAT_STORE[-1].metadata.global_nonce


@pytest.mark.asyncio
async def test_a_single_event_over_the_limit_is_named_not_skipped() -> None:
    """No page size can carry an event larger than the transport limit. The
    check must not step over it (it could be the dropped start) and must say
    where it is stuck, so the watch logs something an operator can act on."""
    checkpoints = MemoryCheckpointStore()
    listing = WorkflowExecutionListProjection(InMemoryProjectionStore())
    detail = WorkflowExecutionDetailProjection(InMemoryProjectionStore())
    await _project([listing, detail], checkpoints, _FAT_STORE, drop=None)
    store = _ByteLimitedStore(_FAT_STORE, max_bytes=10_000)  # below one event
    detector = UnappliedStartDetector(
        store, checkpoints, (listing, detail), is_settled=_settled
    )

    with pytest.raises(OversizedEventError) as raised:
        await detector.check()

    # A first scan reads from the start of the store; the event is the first one after it.
    assert raised.value.from_global_nonce == 1
    assert "at or after global nonce 1 " in str(raised.value)
    assert store.refused == 1 + _PAGE_SIZE_HALVINGS
