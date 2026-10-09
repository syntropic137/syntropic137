"""What the ESP v0.17.0 coordinator knows, the service must pass on.

Three things the coordinator started doing in v0.17.0 that are invisible from
outside unless this service forwards them:

* A projection that fails an event is HELD below it and retried (ESP #391),
  while every other projection keeps consuming. Nothing else on /health moves,
  so a hold is silent unless ``get_status`` reports it.
* An undecodable stored event HALTS the subscription (ADR-026). With
  ``undecodable_recheck_interval`` set the coordinator stays halted inside
  ``start()`` rather than raising, so ``running`` stays True and only
  ``halted_at`` says the read path stopped.
* The coordinator filters by type before decoding (ADR-027), but only for a
  store whose ``subscribe`` declares ``event_types``. It reads that off the
  store it is GIVEN, which here is ``_SignalsWhenSubscribed``; a wrapper that
  drops the parameter turns filtering off without an error anywhere.

Each test drives the real ``SubscriptionCoordinator`` over a store double.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, ClassVar

import pytest
from event_sourcing import CheckpointedProjection, ProjectionResult
from event_sourcing.core.errors import EventPayloadError
from event_sourcing.core.event import DomainEvent, EventEnvelope, EventMetadata
from event_sourcing.stores.memory_checkpoint import MemoryCheckpointStore

from syn_adapters.subscriptions.coordinator_service import (
    CoordinatorSubscriptionService,
    HeldProjection,
    SubscriptionServiceStatus,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable

    from event_sourcing.core.envelope import EventTypeFilter

BOOM = "Boom"
BOOM_NONCE = 7


class _Boom(DomainEvent):
    event_type: ClassVar[str] = BOOM


def _envelope() -> EventEnvelope[DomainEvent]:
    return EventEnvelope[DomainEvent](
        event=_Boom(),
        metadata=EventMetadata(
            aggregate_nonce=1,
            aggregate_id="a",
            aggregate_type="A",
            global_nonce=BOOM_NONCE,
            event_type=BOOM,
        ),
    )


class _Failing(CheckpointedProjection):
    """Fails every event it is given, as a handler with a deterministic bug does."""

    def get_name(self) -> str:
        return "failing_projection"

    def get_version(self) -> int:
        return 1

    def get_subscribed_event_types(self) -> set[str] | None:
        return {BOOM}

    async def handle_event(
        self,
        envelope: EventEnvelope[DomainEvent],
        checkpoint_store: object,
        context: object = None,
    ) -> ProjectionResult:
        del envelope, checkpoint_store, context
        return ProjectionResult.FAILURE


class _FilteringStore:
    """A store with the v0.17.0 ``subscribe`` signature: it can filter by type.

    Delivers the one event, then parks, and records every filter it was given
    as what it answered at that moment: the coordinator's filter is read live,
    and a held projection leaves its track's filter once it is held.
    ``undecodable`` makes the stream fail at the event the way the gRPC client
    does when the payload will not decode.
    """

    def __init__(self, *, undecodable: bool = False) -> None:
        self._undecodable = undecodable
        #: Per subscribe: None when no filter came, else (wants Boom, wants other).
        self.filters: list[tuple[bool, bool] | None] = []
        self._parked = asyncio.Event()

    async def read_all(
        self,
        from_global_nonce: int = 0,
        max_count: int = 100,
        forward: bool = True,
    ) -> tuple[list[EventEnvelope[DomainEvent]], bool, int]:
        del from_global_nonce, max_count, forward
        return [_envelope()], True, BOOM_NONCE

    async def subscribe(
        self, from_global_nonce: int = 0, event_types: EventTypeFilter | None = None
    ) -> AsyncIterator[EventEnvelope[DomainEvent]]:
        del from_global_nonce
        self.filters.append(
            None
            if event_types is None
            else (BOOM in event_types, "SomethingNoProjectionHandles" in event_types)
        )
        if self._undecodable:
            raise EventPayloadError(BOOM, 1, "payload does not validate", BOOM_NONCE)
        yield _envelope()
        await self._parked.wait()


async def _until(
    service: CoordinatorSubscriptionService,
    reached: Callable[[SubscriptionServiceStatus], bool],
) -> SubscriptionServiceStatus:
    async def wait() -> SubscriptionServiceStatus:
        while not reached(status := service.get_status()):
            await asyncio.sleep(0.01)
        return status

    return await asyncio.wait_for(wait(), timeout=10)


async def _started(store: _FilteringStore) -> CoordinatorSubscriptionService:
    service = CoordinatorSubscriptionService(
        event_store=store,  # type: ignore[arg-type]  # double, not EventStoreClient
        projections=[_Failing()],
        checkpoint_store=MemoryCheckpointStore(),
    )
    await service.start()
    return service


@pytest.mark.unit
@pytest.mark.asyncio
async def test_a_held_projection_is_in_the_status() -> None:
    service = await _started(_FilteringStore())
    try:
        status = await _until(service, lambda s: bool(s.held_projections))
    finally:
        await service.stop()

    assert status.held_projections == (
        HeldProjection(
            projection_name="failing_projection", event_type=BOOM, global_nonce=BOOM_NONCE
        ),
    )
    assert status.halted_at is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_the_type_filter_reaches_the_store() -> None:
    store = _FilteringStore()
    service = await _started(store)
    try:
        await _until(service, lambda s: bool(s.held_projections))
    finally:
        await service.stop()

    # One subscription per track (the replay track the projection starts on,
    # the live track, the retry track it is held on); every one is filtered.
    assert store.filters, "the coordinator never subscribed"
    assert None not in store.filters, "the wrapper dropped event_types: nothing is filtered"
    # The track that carried the projection asked for its type and nothing else.
    assert (True, False) in store.filters


@pytest.mark.unit
@pytest.mark.asyncio
async def test_an_undecodable_event_halts_and_says_where(
    caplog: pytest.LogCaptureFixture,
) -> None:
    service = await _started(_FilteringStore(undecodable=True))
    try:
        status = await _until(service, lambda s: s.halted_at is not None)
        # Long enough for start() to have raised and the reconnect loop to log.
        await asyncio.sleep(0.2)
    finally:
        await service.stop()

    # The coordinator re-checks the halt itself. Had start() raised instead,
    # the service's reconnect loop would report it as a transient error and
    # replay to the same event on every attempt.
    assert not [
        r
        for r in caplog.records
        if r.name == "syn_adapters.subscriptions.coordinator_helpers" and r.levelname == "ERROR"
    ]

    assert status.halted_at == BOOM_NONCE
    # Halted inside start(), not crashed out of it: the service still runs and
    # re-checks, so `running` alone would have called this healthy.
    assert status.running is True
