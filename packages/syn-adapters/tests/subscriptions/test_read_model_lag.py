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

The second signal, `is_stalled`, covers the case the first deliberately cannot:
a projection behind the head with NO replay running, its checkpoint frozen. That
one does not end by itself, so reporting it healthy is worse than the blackout
above. The two are pinned as INDEPENDENTLY observable — each has a test where it
is set and the other is not — because a payload where they move together tells
an operator no more than one flag would.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
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
from syn_adapters.subscriptions.read_model_lag import (
    STALLED_AFTER_SECONDS,
    CheckpointState,
    measure_read_model_lag,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

# The measured deploy: head at 8726, session_summaries replaying from 0 and
# reached 4142, everything else frozen at its pre-deploy position of 8722.
HEAD = 8726
REBUILDING = "session_summaries"
REBUILDING_POSITION = 4142
FROZEN_POSITION = 8722
PEERS = ("workflow_executions", "workflow_execution_details", "dashboard_metrics")

# Ages either side of the stall threshold. FRESH is the mid-dispatch sample a
# busy deployment produces constantly; FROZEN is past anything the coordinator's
# own reconnect backoff can explain.
NOW = datetime(2025, 11, 3, 6, 9, 35, tzinfo=UTC)
FRESH = NOW - timedelta(seconds=1)
FROZEN = NOW - timedelta(seconds=STALLED_AFTER_SECONDS + 1)


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
    frozen_checkpoint: str | None = None,
    live: bool = False,
) -> CoordinatorSubscriptionService:
    """A started service whose projections sit at the given checkpoints.

    ``without_checkpoint`` registers a projection with no checkpoint row, which
    is what a projection looks like between ``delete_checkpoint`` and the first
    save of its replay.

    ``frozen_checkpoint`` backdates one projection's ``updated_at`` past the
    stall threshold: the row a projection leaves behind when it stops advancing.
    Every other checkpoint is written as of now, so the fixture cannot pass by
    making everything look stale.

    ``live`` puts the coordinator past its live boundary, which is the state it
    reaches by dispatching an event above the boundary it snapshotted. Set here
    because the parked stream never delivers one, and a wedged projection is
    only reachable with the coordinator live - that combination is the whole
    point of the second signal.
    """
    checkpoint_store = MemoryCheckpointStore()
    now = datetime.now(UTC)
    for name, position in positions.items():
        stale = name == frozen_checkpoint
        await checkpoint_store.save_checkpoint(
            ProjectionCheckpoint(
                projection_name=name,
                global_position=position,
                updated_at=now - timedelta(seconds=STALLED_AFTER_SECONDS + 1) if stale else now,
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
    if live:
        # Private: the service exposes no seam for this state, and inventing one
        # would add production API that only a test uses.
        coordinator = service._coordinator
        assert coordinator is not None
        coordinator.is_catching_up = False
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
    # A rebuild whose checkpoints are still moving is not stuck. Asserted here so
    # the two signals cannot quietly collapse into one that means "behind".
    assert lag.is_stalled is False
    assert [entry.stalled for entry in lag.lagging_projections] == [False, False, False, False]


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
    assert lag.is_stalled is False
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
    healthy system degraded at random, and the flag would stop being read.

    (c) The anti-flapping guarantee, now covering BOTH signals: ordinary
    eventual-consistency lag with a checkpoint that just moved is healthy, and
    adding the stall signal must not have quietly made it degraded.
    """
    lag = measure_read_model_lag(
        head_position=HEAD,
        checkpoints={REBUILDING: CheckpointState(position=HEAD - 1, updated_at=FRESH)},
        projection_names=[REBUILDING],
        replaying=False,
        now=NOW,
    )

    assert lag.is_catching_up is False
    assert lag.is_stalled is False
    # Still measured and reported — the flags are gated, the facts are not.
    assert lag.lagging_projections[0].lag == 1
    assert lag.lagging_projections[0].stalled is False
    assert lag.lagging_projections[0].checkpoint_age_seconds == 1


@pytest.mark.unit
def test_a_finished_replay_on_a_quiet_store_is_not_still_catching_up() -> None:
    """The coordinator flips to live only when it dispatches an event ABOVE its
    boundary, so after a completed replay with no further writes its own flag
    stays True indefinitely. Trusting it alone would report a finished rebuild
    as still running."""
    lag = measure_read_model_lag(
        head_position=HEAD,
        checkpoints={REBUILDING: CheckpointState(position=HEAD, updated_at=FROZEN)},
        projection_names=[REBUILDING],
        replaying=True,
        now=NOW,
    )

    assert lag.is_catching_up is False
    # And a long-untouched checkpoint that is AT the head is not stalled either:
    # a quiet store leaves every checkpoint old, and calling that stuck would
    # degrade an idle deployment permanently.
    assert lag.is_stalled is False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_a_wedged_projection_is_reported_with_no_replay_running() -> None:
    """(b) The case the catch-up flag deliberately cannot see, off the service.

    A projection that keeps failing on the events it is handed never advances
    its checkpoint, while the coordinator stays live and its peers keep up.
    Before this signal that read back as `is_catching_up: false`, no flag, and a
    healthy verdict on a read model that is stuck until someone intervenes.

    Driven through `describe_read_model_lag` rather than the measurement alone
    because the hop that matters is the one in between: the service has to carry
    `updated_at` off the checkpoint row, and dropping it there would leave every
    test either side of it passing.
    """
    service = await _service_at(
        {REBUILDING: FROZEN_POSITION - 1} | dict.fromkeys(PEERS, HEAD),
        frozen_checkpoint=REBUILDING,
        live=True,
    )
    try:
        lag = await service.describe_read_model_lag()
    finally:
        await service.stop()

    assert lag is not None
    assert lag.is_stalled is True
    # Independently observable: this is NOT a rebuild, and must not claim to be.
    assert lag.is_catching_up is False
    # Named, so the operator knows where to look.
    assert [entry.projection for entry in lag.lagging_projections] == [REBUILDING]
    assert lag.lagging_projections[0].stalled is True
    age = lag.lagging_projections[0].checkpoint_age_seconds
    assert age is not None
    assert age > STALLED_AFTER_SECONDS


@pytest.mark.unit
@pytest.mark.asyncio
async def test_a_replay_that_wedges_raises_both_signals() -> None:
    """Neither signal masks the other: a rebuild that gets stuck is both.

    Gating the stall signal on "no replay running" would read naturally and
    would reintroduce the blind spot inside the exact window this module was
    written for — the 8m46s where nobody could tell a slow rebuild from a
    broken one.
    """
    service = await _service_at(
        {REBUILDING: REBUILDING_POSITION} | dict.fromkeys(PEERS, FROZEN_POSITION),
        frozen_checkpoint=REBUILDING,
    )
    try:
        lag = await service.describe_read_model_lag()
    finally:
        await service.stop()

    assert lag is not None
    assert lag.is_catching_up is True
    assert lag.is_stalled is True
    assert lag.lagging_projections[0].projection == REBUILDING
    assert lag.lagging_projections[0].stalled is True
    # Only the frozen one. The peers are behind and still moving.
    assert [entry.projection for entry in lag.lagging_projections if entry.stalled] == [REBUILDING]


@pytest.mark.unit
def test_a_projection_with_no_checkpoint_yet_is_not_called_stuck() -> None:
    """A cleared checkpoint has no `updated_at` to be old, and the honest
    reading of "no evidence" is not "stuck". It is still the deepest lag in the
    list, so it is never invisible — see the cleared-checkpoint test above."""
    lag = measure_read_model_lag(
        head_position=HEAD,
        checkpoints={},
        projection_names=[REBUILDING],
        replaying=False,
        now=NOW,
    )

    assert lag.is_stalled is False
    assert lag.lagging_projections[0].checkpoint_age_seconds is None
    assert lag.lagging_projections[0].lag == HEAD
