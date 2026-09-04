"""The read path has to admit when it is behind (#1172).

The incident these cover: a version bump on one projection cleared it, deleted
its checkpoint, and restarted the SHARED subscription from global nonce 0. For
8m46s no projection advanced and freshly dispatched executions 404ed, while
/health reported healthy throughout. The checkpoint table was the only thing
that distinguished "rebuild in progress" from "the platform lost my execution".

These drive the REAL SubscriptionCoordinator through the REAL service method.
The event store double only parks the subscription so the fixture's checkpoint
positions stay put — everything that decides `is_catching_up` (the coordinator's
minimum-position calculation, its live-boundary snapshot, and the measurement
against the store head) is production code here.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import TYPE_CHECKING, ClassVar

import pytest
from event_sourcing.core.checkpoint import (
    CheckpointedProjection,
    ProjectionCheckpoint,
    ProjectionResult,
)
from event_sourcing.core.event import DomainEvent, EventEnvelope, EventMetadata
from event_sourcing.stores.memory_checkpoint import MemoryCheckpointStore

from syn_adapters.subscriptions.coordinator_service import CoordinatorSubscriptionService
from syn_adapters.subscriptions.read_model_lag import measure_read_model_lag

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

# The measured deploy: head at 8726, session_summaries replaying from 0 and
# reached 4142, everything else frozen at its pre-deploy position of 8722.
HEAD = 8726
REBUILDING = "session_summaries"
REBUILDING_POSITION = 4142
FROZEN_POSITION = 8722
PEERS = ("workflow_executions", "workflow_execution_details", "dashboard_metrics")


class _Marker(DomainEvent):
    event_type: ClassVar[str] = "Marker"


class _StubProjection(CheckpointedProjection):
    """Minimal projection: exists to be registered and named."""

    def __init__(self, name: str) -> None:
        self._name = name

    def get_name(self) -> str:
        return self._name

    def get_version(self) -> int:
        return 1

    def get_subscribed_event_types(self) -> set[str] | None:
        return set()

    async def handle_event(
        self,
        envelope: EventEnvelope[DomainEvent],
        checkpoint_store: object,
        context: object = None,
    ) -> ProjectionResult:
        return ProjectionResult.SKIP


class _ParkedEventStore:
    """A store with a head, whose subscription never delivers anything.

    Parking the stream is the whole point: it freezes the coordinator at the
    instant after it computes its live boundary, which is the state a /health
    probe lands in during a real replay. A stream that delivered events would
    race the fixture and drag every checkpoint to the head.
    """

    def __init__(self, head: int) -> None:
        self._head = head
        self.parked = asyncio.Event()

    async def read_all(
        self,
        from_global_nonce: int = 0,
        max_count: int = 100,
        forward: bool = True,
    ) -> tuple[list[EventEnvelope[DomainEvent]], bool, int]:
        envelope = EventEnvelope[DomainEvent](
            event=_Marker(),
            metadata=EventMetadata(
                aggregate_nonce=1,
                aggregate_id="a",
                aggregate_type="A",
                global_nonce=self._head,
                event_type="Marker",
            ),
        )
        return [envelope], True, self._head

    async def subscribe(self, from_global_nonce: int) -> AsyncIterator[EventEnvelope[DomainEvent]]:
        await self.parked.wait()
        return
        yield  # pragma: no cover - unreachable, makes this an async generator


async def _service_at(
    positions: dict[str, int],
    *,
    without_checkpoint: str | None = None,
) -> CoordinatorSubscriptionService:
    """A started service whose projections sit at the given checkpoints.

    ``without_checkpoint`` registers a projection with no checkpoint row, which
    is what a projection looks like between ``delete_checkpoint`` and the first
    save of its replay.
    """
    checkpoint_store = MemoryCheckpointStore()
    for name, position in positions.items():
        await checkpoint_store.save_checkpoint(
            ProjectionCheckpoint(
                projection_name=name,
                global_position=position,
                updated_at=datetime.now(UTC),
                version=1,
            )
        )

    registered = [*positions]
    if without_checkpoint is not None:
        registered.append(without_checkpoint)

    service = CoordinatorSubscriptionService(
        event_store=_ParkedEventStore(HEAD),  # type: ignore[arg-type]  # double, not EventStoreClient
        projections=[_StubProjection(name) for name in registered],
        checkpoint_store=checkpoint_store,
    )
    await service.start()
    return service


@pytest.mark.unit
@pytest.mark.asyncio
async def test_mid_rebuild_names_the_projection_holding_it_up() -> None:
    """The 06:09:35 snapshot from the incident, read back off the service."""
    service = await _service_at(
        {REBUILDING: REBUILDING_POSITION} | dict.fromkeys(PEERS, FROZEN_POSITION)
    )
    try:
        lag = await service.describe_read_model_lag()
    finally:
        await service.stop()

    assert lag is not None
    assert lag.is_catching_up is True
    assert lag.lag == HEAD - REBUILDING_POSITION
    assert lag.head_position == HEAD
    # Furthest behind first, so the first entry answers "which one".
    assert lag.lagging_projections[0].projection == REBUILDING
    assert lag.lagging_projections[0].position == REBUILDING_POSITION
    # The frozen peers are behind too and must not be hidden.
    assert {entry.projection for entry in lag.lagging_projections} == {REBUILDING, *PEERS}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_all_at_head_is_not_catching_up() -> None:
    service = await _service_at(dict.fromkeys((REBUILDING, *PEERS), HEAD))
    try:
        lag = await service.describe_read_model_lag()
    finally:
        await service.stop()

    assert lag is not None
    assert lag.is_catching_up is False
    assert lag.lag == 0
    assert lag.lagging_projections == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_a_cleared_checkpoint_is_the_deepest_lag_not_an_absence() -> None:
    """A projection whose checkpoint was just deleted has no row at all.

    Reading only the rows that exist would report this — the first seconds of
    every rebuild, and the exact moment an operator is most likely to look —
    as nothing lagging at all.
    """
    service = await _service_at(
        dict.fromkeys(PEERS, FROZEN_POSITION), without_checkpoint=REBUILDING
    )
    try:
        lag = await service.describe_read_model_lag()
    finally:
        await service.stop()

    assert lag is not None
    assert lag.lagging_projections[0].projection == REBUILDING
    assert lag.lagging_projections[0].position == 0
    assert lag.lag == HEAD
    assert lag.is_catching_up is True


@pytest.mark.unit
def test_a_live_coordinator_one_event_behind_is_not_a_rebuild() -> None:
    """Checkpoints advance per event, so a mid-dispatch sample finds someone
    one behind on any busy deployment. Raising the flag for that would mark a
    healthy system degraded at random, and the flag would stop being read."""
    lag = measure_read_model_lag(
        head_position=HEAD,
        checkpoints={REBUILDING: HEAD - 1},
        projection_names=[REBUILDING],
        replaying=False,
    )

    assert lag.is_catching_up is False
    # Still measured and reported — the flag is gated, the facts are not.
    assert lag.lagging_projections[0].lag == 1


@pytest.mark.unit
def test_a_finished_replay_on_a_quiet_store_is_not_still_catching_up() -> None:
    """The coordinator flips to live only when it dispatches an event ABOVE its
    boundary, so after a completed replay with no further writes its own flag
    stays True indefinitely. Trusting it alone would report a finished rebuild
    as still running."""
    lag = measure_read_model_lag(
        head_position=HEAD,
        checkpoints={REBUILDING: HEAD},
        projection_names=[REBUILDING],
        replaying=True,
    )

    assert lag.is_catching_up is False
