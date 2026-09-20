"""A trigger paused by a deploy is dispatched when the deploy ends (#1387).

`WorkflowDispatchProjection` parks a trigger that arrives while admission is
closed as a `paused` record, and `_pending_records()` re-offers `paused`
alongside `pending`. That only pays off if something ever calls the processor
side again, and the coordinator calls it in exactly one place: after a
SUBSCRIBED event has been handled live.

Clearing maintenance mode used to be neither. It is a flag going false - not an
event, not a wake-up - so the re-offer waited for the next unrelated GitHub
event to arrive. On a quiet repository, or on the last deploy of the day, that
is never, and "paused" becomes a dropped trigger with a nicer label. The
existing coverage missed it because it called `process_pending()` by hand,
which is the one thing production never does.

The fix is an announcement in the event stream, so these tests run the REAL
`SubscriptionCoordinator` over the REAL projection and let it decide when the
processor side runs. Nothing here calls `process_pending()`; nothing here
publishes a second GitHub event.
"""

from __future__ import annotations

import asyncio
import os
from typing import TYPE_CHECKING, NamedTuple

import pytest
from event_sourcing import DomainEvent, EventEnvelope, EventMetadata
from event_sourcing.stores.memory_checkpoint import MemoryCheckpointStore
from event_sourcing.stores.memory_projection import MemoryProjectionStore
from event_sourcing.subscriptions.coordinator import SubscriptionCoordinator

os.environ.setdefault("APP_ENVIRONMENT", "test")

from syn_adapters.maintenance import EventStoreAdmissionAnnouncer, InMemoryMaintenanceAdapter
from syn_adapters.subscriptions.coordinator_service import (
    CoordinatorSubscriptionService,
    SubscriptionNotLiveError,
)
from syn_api._wiring import BackgroundWorkflowDispatcher
from syn_domain.contexts._shared import (
    AdmissionAnnouncementFailedError,
    AdmissionGate,
    AdmissionTicket,
)
from syn_domain.contexts.github._shared.projection_names import WORKFLOW_DISPATCH
from syn_domain.contexts.github.domain.events.TriggerFiredEvent import TriggerFiredEvent
from syn_domain.contexts.github.slices.dispatch_triggered_workflow.projection import (
    WorkflowDispatchProjection,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from event_sourcing import ProjectionStore

pytestmark = pytest.mark.unit

_PATIENCE = 5.0
#: Loop turns the racy store spends inside its head snapshot. Any number large
#: enough to contain the announcement's own turns will do; what it buys is that
#: an announcement made while `start()` is in flight lands INSIDE the snapshot
#: window every run, rather than sometimes.
_HEAD_SNAPSHOT_TURNS = 50
_EXECUTION_ID = "exec-paused-by-the-deploy"
_TRIGGER_ID = "trg-ci-self-healing"


class _LiveEventStore:
    """An event store whose appends are delivered, the way production's are.

    Only `append_events` is real here, and it is the half that matters: an
    announcement written to the store is picked up by the subscription and
    dispatched to the projections. Pushing it straight into the coordinator is
    the same hop the gRPC subscription makes, minus the network - so a test
    that never touches the coordinator itself still proves the coordinator is
    what runs the processor side.
    """

    def __init__(self) -> None:
        self.appended: list[EventEnvelope[DomainEvent]] = []
        self._coordinator: SubscriptionCoordinator | None = None
        self._next_nonce = 100
        #: The store is down. The shape the happy paths cannot produce: the
        #: durable flag write succeeds and the announcement's append does not.
        self.down = False
        self.append_attempts = 0

    def subscribes(self, coordinator: SubscriptionCoordinator) -> None:
        self._coordinator = coordinator

    async def append_events(
        self,
        stream_name: str,
        events: list[EventEnvelope[DomainEvent]],
        expected_version: int | None = None,
    ) -> None:
        del stream_name, expected_version
        self.append_attempts += 1
        if self.down:
            raise OSError("event store unavailable")
        for envelope in events:
            self.appended.append(envelope)
            await self.deliver(envelope.event, envelope.metadata)

    async def deliver(self, event: DomainEvent, metadata: EventMetadata | None = None) -> None:
        """Hand one event to the coordinator as a live event."""
        assert self._coordinator is not None
        self._next_nonce += 1
        base = metadata or EventMetadata(
            event_type=event.event_type,
            aggregate_id=_TRIGGER_ID,
            aggregate_type="TriggerRule",
            aggregate_nonce=1,
        )
        await self._coordinator.dispatch_event(
            EventEnvelope(
                event=event,
                metadata=base.model_copy(update={"global_nonce": self._next_nonce}),
            )
        )


class _RecordingHandler:
    """The execution handler, reduced to "it was reached and it became durable"."""

    def __init__(self) -> None:
        self.executions: list[str] = []

    async def validate_stored_declarations(self, _workflow_id: str) -> None:
        return None

    async def handle(self, command: object, *, admitted: AdmissionTicket | None = None) -> None:
        self.executions.append(getattr(command, "execution_id", "") or "")
        if admitted is not None:
            admitted.mark_visible()


class _Api:
    """One API process: a gate, a dispatcher, a projection and a coordinator.

    Built as a unit so a "restart" can be expressed as a second one over the
    same durable state - the maintenance store and the projection store - with
    everything process-local thrown away, which is what a restart is.
    """

    def __init__(
        self,
        *,
        port: InMemoryMaintenanceAdapter,
        projection_store: ProjectionStore,
    ) -> None:
        self.store = _LiveEventStore()
        self.gate = AdmissionGate(port, EventStoreAdmissionAnnouncer(self.store))  # type: ignore[arg-type]
        self.handler = _RecordingHandler()
        self.dispatcher = BackgroundWorkflowDispatcher(
            self.handler,  # type: ignore[arg-type]
            maintenance=self.gate,
        )
        self.projection = WorkflowDispatchProjection(
            execution_service=self.dispatcher,
            store=projection_store,
        )
        self.checkpoints = MemoryCheckpointStore()
        self.coordinator = SubscriptionCoordinator(
            event_store=self.store,  # type: ignore[arg-type]
            checkpoint_store=self.checkpoints,
            projections=[self.projection],
        )
        # A process that is already live: caught up, so ProcessManagers are
        # allowed to run their processor side. Set by hand because these tests
        # are about what an announcement DOES once it is observed live, and a
        # real coordinator reaches this state after replay anyway.
        #
        # It is deliberately not how a real process gets here, and that gap is
        # its own bug: `TestTheRestartWakeRacesTheCoordinator` drives the real
        # startup path, where reaching this state is exactly what is in doubt.
        self.coordinator.live_boundary_nonce = 0
        self.coordinator.is_catching_up = False
        self.store.subscribes(self.coordinator)
        self._projection_store = projection_store

    async def a_trigger_fires(self) -> None:
        await self.store.deliver(
            TriggerFiredEvent(
                trigger_id=_TRIGGER_ID,
                execution_id=_EXECUTION_ID,
                workflow_id="wf-ci-self-healing",
                workflow_inputs={"repository": "syntropic137/syntropic137"},
                github_event_type="check_run.completed",
            )
        )

    async def record_status(self) -> str:
        found = await self._projection_store.get(WORKFLOW_DISPATCH, _EXECUTION_ID)
        assert found is not None, "the trigger produced no dispatch record at all"
        return str(found.get("status", ""))

    async def settle(self) -> None:
        """Let the fire-and-forget execution tasks finish, so a lease left
        outstanding shows up as a failure here rather than as a hang later."""
        async with asyncio.timeout(_PATIENCE):
            while self.dispatcher._tasks:
                await asyncio.gather(*self.dispatcher._tasks, return_exceptions=True)
                await asyncio.sleep(0)


async def _a_deploy_pauses_a_trigger(api: _Api) -> None:
    await api.gate.set_mode(active=True, reason="pit stop", actor="deploy")
    await api.a_trigger_fires()
    assert await api.record_status() == "paused", (
        "the trigger was not held back, so there is nothing for this test to wake"
    )
    assert api.handler.executions == []


class TestATriggerHeldBackByADeploy:
    async def test_is_dispatched_when_maintenance_clears(self) -> None:
        """No further GitHub events. The only thing that happens after the
        trigger is the operator clearing maintenance mode."""
        api = _Api(port=InMemoryMaintenanceAdapter(), projection_store=MemoryProjectionStore())
        await _a_deploy_pauses_a_trigger(api)

        await api.gate.set_mode(active=False, reason="", actor="deploy")
        await api.settle()

        assert await api.record_status() == "dispatched", (
            "maintenance cleared and the paused trigger was never re-offered; "
            "nothing else will ever prompt it (#1387, finding B)"
        )
        assert api.handler.executions == [_EXECUTION_ID]

    async def test_the_wake_is_in_the_event_stream(self) -> None:
        """Durable, not a callback. The announcement has to outlive the process
        that made it or the restart below has nothing to work from."""
        api = _Api(port=InMemoryMaintenanceAdapter(), projection_store=MemoryProjectionStore())
        await _a_deploy_pauses_a_trigger(api)

        await api.gate.set_mode(active=False, reason="", actor="deploy")
        await api.settle()

        announcements = [
            envelope
            for envelope in api.store.appended
            if envelope.metadata.event_type == "maintenance.AdmissionOpen"
        ]
        assert len(announcements) == 1, (
            "clearing maintenance wrote no announcement to the event store, so "
            "a process that was not running at that moment cannot learn of it"
        )

    async def test_closing_the_gate_announces_nothing(self) -> None:
        """The negative control. An announcement while admission is shut would
        wake the dispatcher into a refusal and re-pause everything it tried."""
        api = _Api(port=InMemoryMaintenanceAdapter(), projection_store=MemoryProjectionStore())
        await api.gate.set_mode(active=True, reason="pit stop", actor="deploy")

        assert api.store.appended == []


class _RecordingAnnouncer:
    """Records the announcement instead of writing it, for the wiring test."""

    def __init__(self) -> None:
        self.announcements: list[bool] = []

    async def announce_open(self, mode: object, *, after_restart: bool) -> None:
        del mode
        self.announcements.append(after_restart)


class TestStartupItself:
    """The startup half has to be WIRED, not merely available.

    `_init_subscriptions` is where a process learns it is live, so it is where
    the re-announcement belongs; a helper nobody calls would leave every
    restart silent and this whole mechanism resting on the process that cleared
    maintenance surviving.

    Only the wiring - announced, or quiet - which is why a stub coordinator is
    enough here. Whether the announcement is heard LIVE is a different question
    and a different class: `TestTheRestartWakeRacesTheCoordinator`.
    """

    async def _run_init_subscriptions(
        self, monkeypatch: pytest.MonkeyPatch, *, paused: bool
    ) -> _RecordingAnnouncer:
        from syn_api.services import lifecycle

        announcer = _RecordingAnnouncer()
        gate = AdmissionGate(InMemoryMaintenanceAdapter(), announcer)  # type: ignore[arg-type]
        if paused:
            await gate.set_mode(active=True, reason="pit stop", actor="deploy")
            announcer.announcements.clear()

        class _Coordinator:
            def __init__(self) -> None:
                self.started = False

            async def start(self) -> None:
                self.started = True

        monkeypatch.setattr(lifecycle, "get_admission_gate", lambda: gate)
        monkeypatch.setattr(lifecycle, "get_realtime", lambda: None)
        monkeypatch.setattr(
            lifecycle, "get_subscription_coordinator", lambda **_kwargs: _Coordinator()
        )
        state = lifecycle.LifecycleState()
        state.workflow_dispatcher = object()  # type: ignore[assignment]

        await lifecycle._init_subscriptions(state)
        return announcer

    async def test_announces_that_admission_is_open(self, monkeypatch: pytest.MonkeyPatch) -> None:
        announcer = await self._run_init_subscriptions(monkeypatch, paused=False)
        assert announcer.announcements == [True], (
            "a started API never re-announced that admission is open, so a "
            "trigger paused by the deploy before it has no second prompt"
        )

    async def test_stays_quiet_when_admission_is_paused(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        announcer = await self._run_init_subscriptions(monkeypatch, paused=True)
        assert announcer.announcements == []


class TestTheApiThatCrashesBeforeDraining:
    """The wake must survive a restart.

    Clearing maintenance and then losing the process - a crash, or the deploy's
    own container swap - leaves the `paused` records in the projection store
    and no second prompt, because a flag that is already false never becomes
    false again. So the next process announces on startup.
    """

    async def test_the_next_process_dispatches_the_paused_trigger(self) -> None:
        port = InMemoryMaintenanceAdapter()
        projection_store = MemoryProjectionStore()

        died = _Api(port=port, projection_store=projection_store)
        await _a_deploy_pauses_a_trigger(died)
        # Cleared through the port, not the gate: the flag reached the durable
        # store and the process was gone before it could announce anything.
        await port.set_mode(active=False, reason="", actor="deploy")

        restarted = _Api(port=port, projection_store=projection_store)
        assert await restarted.record_status() == "paused", (
            "the paused record did not survive into the new process"
        )

        # What `_init_subscriptions` does once the coordinator is running.
        await restarted.gate.announce_open(await restarted.gate.current(), after_restart=True)
        await restarted.settle()

        assert await restarted.record_status() == "dispatched", (
            "the trigger stayed paused across a restart; the wake did not "
            "survive the process that cleared maintenance (#1387, finding B)"
        )
        assert restarted.handler.executions == [_EXECUTION_ID]

    async def test_a_restart_during_the_deploy_announces_nothing(self) -> None:
        """An API that comes up mid-deploy must stay shut and stay quiet."""
        port = InMemoryMaintenanceAdapter()
        projection_store = MemoryProjectionStore()

        died = _Api(port=port, projection_store=projection_store)
        await _a_deploy_pauses_a_trigger(died)

        restarted = _Api(port=port, projection_store=projection_store)
        mode = await restarted.gate.current()
        assert mode.active is True
        # The startup hook's own condition, asserted rather than re-implemented.
        if not mode.active:  # pragma: no cover - the flag is set above
            await restarted.gate.announce_open(mode, after_restart=True)

        assert restarted.store.appended == []
        assert await restarted.record_status() == "paused"


class TestAClearThatCouldNotAnnounce:
    """A failed wake is not a finished clear (#1387).

    `set_mode(active=False)` writes the flag and then announces. Swallowing a
    failure there tells the operator the deploy's last step succeeded while the
    triggers it paused are still parked with nothing left to prompt them: no
    later GitHub event is guaranteed, and the flag will never go false a second
    time. Only the operator can retry, so only the operator can be told - which
    is why the gate raises rather than logging and returning a mode.
    """

    async def test_the_clear_does_not_report_success(self) -> None:
        api = _Api(port=InMemoryMaintenanceAdapter(), projection_store=MemoryProjectionStore())
        await _a_deploy_pauses_a_trigger(api)
        api.store.down = True

        with pytest.raises(AdmissionAnnouncementFailedError):
            await api.gate.set_mode(active=False, reason="", actor="deploy")

        assert api.store.append_attempts == 1
        assert api.store.appended == []
        assert await api.record_status() == "paused", (
            "the announcement failed, so the trigger is still parked - a clear "
            "that returned a mode here would report the deploy finished over "
            "work that nothing will ever re-offer (#1387)"
        )

    async def test_the_flag_is_open_all_the_same(self) -> None:
        """The failure belongs to the announcement, not to the flag.

        Worth pinning because it decides what the caller should do next:
        admission IS open, so the repair is to re-announce, not to re-clear a
        gate that is no longer shut.
        """
        api = _Api(port=InMemoryMaintenanceAdapter(), projection_store=MemoryProjectionStore())
        await _a_deploy_pauses_a_trigger(api)
        api.store.down = True

        with pytest.raises(AdmissionAnnouncementFailedError):
            await api.gate.set_mode(active=False, reason="", actor="deploy")

        assert (await api.gate.current()).active is False

    async def test_the_retry_wakes_the_exact_paused_record(self) -> None:
        """What the raise buys: the operator repeats the clear and the record
        this deploy paused is dispatched, with no further GitHub event."""
        api = _Api(port=InMemoryMaintenanceAdapter(), projection_store=MemoryProjectionStore())
        await _a_deploy_pauses_a_trigger(api)
        api.store.down = True

        with pytest.raises(AdmissionAnnouncementFailedError):
            await api.gate.set_mode(active=False, reason="", actor="deploy")

        api.store.down = False
        await api.gate.set_mode(active=False, reason="", actor="deploy")
        await api.settle()

        assert [e.metadata.event_type for e in api.store.appended] == ["maintenance.AdmissionOpen"]
        assert await api.record_status() == "dispatched", (
            "the retried clear announced, but the paused record was not woken"
        )
        assert api.handler.executions == [_EXECUTION_ID]

    async def test_startup_still_only_logs(self) -> None:
        """Startup keeps the other policy, and that is not an inconsistency.

        There is no operator on the startup path to hand a failure to, and the
        next start is itself the retry; raising there would only turn a missed
        wake into a boot loop. So `_announce_admission_if_open` catches, and
        this asserts the gate lets it - the raise is what the CALLER chooses to
        do with, not something the gate has already decided.
        """
        from syn_api.services import lifecycle

        api = _Api(port=InMemoryMaintenanceAdapter(), projection_store=MemoryProjectionStore())
        api.store.down = True

        with pytest.raises(AdmissionAnnouncementFailedError):
            await api.gate.announce_open(await api.gate.current(), after_restart=True)

        # The startup hook's own body, over the same broken store.
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(lifecycle, "get_admission_gate", lambda: api.gate)
            await lifecycle._announce_admission_if_open()

        assert api.store.append_attempts == 2


class _RacyEventStore:
    """A store whose head snapshot takes turns to come back, as a real one does.

    The whole of this race is "what was in the store when the coordinator read
    the head", so a test has to be able to put something there DURING that
    read. An instant fake cannot: it returns before the announcement can be
    made, which is the fixed behaviour handed to the test for free.

    The turns are not timing. The announcement either lands inside the snapshot
    window - and is then backlog, at or below the boundary - or `start()` held
    it until after the subscription was open. There is nothing in between, so
    the test is deterministic in both directions.
    """

    def __init__(self) -> None:
        self.appended: list[EventEnvelope[DomainEvent]] = []
        self._live: asyncio.Queue[EventEnvelope[DomainEvent]] = asyncio.Queue()
        self._next_nonce = 100

    async def append_events(
        self,
        stream_name: str,
        events: list[EventEnvelope[DomainEvent]],
        expected_version: int | None = None,
    ) -> None:
        del stream_name, expected_version
        for envelope in events:
            self._next_nonce += 1
            stamped = EventEnvelope(
                event=envelope.event,
                metadata=envelope.metadata.model_copy(update={"global_nonce": self._next_nonce}),
            )
            self.appended.append(stamped)
            self._live.put_nowait(stamped)

    async def read_all(
        self,
        from_global_nonce: int = 0,
        max_count: int = 100,
        forward: bool = True,
    ) -> tuple[list[EventEnvelope[DomainEvent]], bool, int]:
        del from_global_nonce, max_count
        for _ in range(_HEAD_SNAPSHOT_TURNS):
            await asyncio.sleep(0)
        if not forward:
            return (self.appended[-1:], True, 0)
        return (list(self.appended), True, self._next_nonce + 1)

    def subscribe(self, from_global_nonce: int = 0) -> AsyncIterator[EventEnvelope[DomainEvent]]:
        del from_global_nonce
        return self._stream()

    async def _stream(self) -> AsyncIterator[EventEnvelope[DomainEvent]]:
        while True:
            yield await self._live.get()


class _RestartedApi(NamedTuple):
    """The pieces of one restarted process a test needs to look at."""

    service: CoordinatorSubscriptionService
    store: _RacyEventStore
    checkpoints: MemoryCheckpointStore
    dispatcher: BackgroundWorkflowDispatcher
    handler: _RecordingHandler
    projection_store: ProjectionStore


class TestTheRestartWakeRacesTheCoordinator:
    """A started coordinator is not a live one, and startup announces into that gap.

    `_init_subscriptions` calls `coordinator.start()` and announces as soon as
    it returns. If "started" means only that a task object exists, the
    announcement can be appended before the coordinator has snapshotted the
    store head - and then the announcement IS the head. It arrives at the
    boundary rather than above it, so the coordinator stays in catch-up, never
    runs the processor side, and the paused record the restart was supposed to
    release stays paused with nothing left to prompt it.

    The failure is silent in every place an operator would look: the deploy
    cleared cleanly, the API is up, the announcement is in the event store and
    was delivered to the projection. Only the work never moves.

    So these drive the PRODUCTION startup path over a real
    `CoordinatorSubscriptionService`, a real `SubscriptionCoordinator` and the
    real projection, and let them decide. Nothing here sets `is_catching_up`,
    and nothing here calls `process_pending()`.
    """

    async def _restart_through_init_subscriptions(
        self,
        monkeypatch: pytest.MonkeyPatch,
        *,
        port: InMemoryMaintenanceAdapter,
        projection_store: ProjectionStore,
    ) -> _RestartedApi:
        """Boot one process the way `lifespan` does, and announce as it does."""
        from syn_api.services import lifecycle

        store = _RacyEventStore()
        gate = AdmissionGate(port, EventStoreAdmissionAnnouncer(store))  # type: ignore[arg-type]
        handler = _RecordingHandler()
        dispatcher = BackgroundWorkflowDispatcher(
            handler,  # type: ignore[arg-type]
            maintenance=gate,
        )
        checkpoints = MemoryCheckpointStore()
        service = CoordinatorSubscriptionService(
            event_store=store,  # type: ignore[arg-type]
            projections=[
                WorkflowDispatchProjection(execution_service=dispatcher, store=projection_store)
            ],
            checkpoint_store=checkpoints,
        )
        monkeypatch.setattr(lifecycle, "get_admission_gate", lambda: gate)
        monkeypatch.setattr(lifecycle, "get_realtime", lambda: None)
        monkeypatch.setattr(lifecycle, "get_subscription_coordinator", lambda **_kwargs: service)
        state = lifecycle.LifecycleState()
        state.workflow_dispatcher = dispatcher  # type: ignore[assignment]

        await lifecycle._init_subscriptions(state)
        assert store.appended, "startup announced nothing at all; wrong bug"
        return _RestartedApi(
            service=service,
            store=store,
            checkpoints=checkpoints,
            dispatcher=dispatcher,
            handler=handler,
            projection_store=projection_store,
        )

    async def _once_the_announcement_was_handled(self, api: _RestartedApi) -> None:
        """Wait for the coordinator to have SEEN the announcement.

        It gets there either way - live or as backlog - so every assertion
        after this one is about what the coordinator decided, never about
        whether it had got round to it yet. Without this wait the broken
        behaviour is indistinguishable from the not-yet behaviour, and a test
        that asserts too early passes for the wrong reason.
        """
        announced_at = api.store.appended[-1].metadata.global_nonce or 0
        async with asyncio.timeout(_PATIENCE):
            while True:
                checkpoint = await api.checkpoints.get_checkpoint(WORKFLOW_DISPATCH)
                if checkpoint is not None and checkpoint.global_position >= announced_at:
                    return
                await asyncio.sleep(0)

    async def test_the_restarted_api_dispatches_the_paused_trigger(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        port = InMemoryMaintenanceAdapter()
        projection_store = MemoryProjectionStore()

        died = _Api(port=port, projection_store=projection_store)
        await _a_deploy_pauses_a_trigger(died)
        # Cleared through the port: the flag reached the durable store and the
        # process was gone before it could announce. The restart is the only
        # wake this record will ever get.
        await port.set_mode(active=False, reason="", actor="deploy")

        api = await self._restart_through_init_subscriptions(
            monkeypatch, port=port, projection_store=projection_store
        )
        try:
            await self._once_the_announcement_was_handled(api)
            async with asyncio.timeout(_PATIENCE):
                while api.dispatcher._tasks:
                    await asyncio.gather(*api.dispatcher._tasks, return_exceptions=True)
                    await asyncio.sleep(0)

            found = await projection_store.get(WORKFLOW_DISPATCH, _EXECUTION_ID)
            assert found is not None
            assert str(found.get("status", "")) == "dispatched", (
                "the restart announced that admission was open and the "
                "coordinator read its own announcement as history, so the "
                "processor side never ran and the trigger the deploy paused is "
                "still parked (#1387, finding B)"
            )
            assert api.handler.executions == [_EXECUTION_ID]
        finally:
            await api.service.stop()

    async def test_the_announcement_is_above_the_live_boundary(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The same guarantee, stated as the property rather than its effect.

        Worth having separately because the effect above can be restored by
        luck - an extra event, a different order - while the announcement is
        still being read as history. This one names what `start()` now owes its
        caller, so giving it up has to be deliberate.
        """
        api = await self._restart_through_init_subscriptions(
            monkeypatch,
            port=InMemoryMaintenanceAdapter(),
            projection_store=MemoryProjectionStore(),
        )
        try:
            await self._once_the_announcement_was_handled(api)

            coordinator = api.service._coordinator
            assert coordinator is not None
            announced_at = api.store.appended[-1].metadata.global_nonce or 0
            assert coordinator.live_boundary_nonce < announced_at, (
                "the coordinator's live boundary includes the startup "
                "announcement, so the announcement is history to it and the "
                "processor side will not run for it (#1387, finding B)"
            )
            assert coordinator.is_catching_up is False, (
                "the announcement was handled and the coordinator is still in "
                "catch-up, so no ProcessManager may run its processor side"
            )
        finally:
            await api.service.stop()


class _NeverLiveEventStore:
    """A store whose head read never comes back, as an unreachable one does.

    The coordinator snapshots the head and only then subscribes, so a read
    that never returns IS a subscription that never opens - the one state the
    start deadline exists for. Nothing here is timing: the read blocks on an
    event nobody sets, so the deadline is the only way out and the test cannot
    pass by being lucky about ordering.
    """

    def __init__(self) -> None:
        self.appended: list[EventEnvelope[DomainEvent]] = []
        self.subscribed = False
        self._never = asyncio.Event()

    async def append_events(
        self,
        stream_name: str,
        events: list[EventEnvelope[DomainEvent]],
        expected_version: int | None = None,
    ) -> None:
        del stream_name, expected_version
        self.appended.extend(events)

    async def read_all(
        self,
        from_global_nonce: int = 0,
        max_count: int = 100,
        forward: bool = True,
    ) -> tuple[list[EventEnvelope[DomainEvent]], bool, int]:
        del from_global_nonce, max_count, forward
        await self._never.wait()
        raise AssertionError("the head read was released; nothing should set that event")

    def subscribe(self, from_global_nonce: int = 0) -> AsyncIterator[EventEnvelope[DomainEvent]]:
        del from_global_nonce
        self.subscribed = True
        return self._nothing()

    async def _nothing(self) -> AsyncIterator[EventEnvelope[DomainEvent]]:
        empty: list[EventEnvelope[DomainEvent]] = []
        for envelope in empty:  # pragma: no cover - there is never one
            yield envelope
        await self._never.wait()


class TestTheEventStoreThatNeverGoesLive:
    """A start that cannot reach the boundary must FAIL, not announce anyway.

    `TestTheRestartWakeRacesTheCoordinator` pins the normal path: `start()`
    waits, so the announcement lands above the live boundary. This is the
    other exit from that wait. A deadline that logged and returned would leave
    `start()` meaning "live" on one path and "a task exists" on the other,
    with nothing at the call site able to tell which it got - and
    `_init_subscriptions` announces the moment it returns. That is the same
    stranded trigger as finding B, arriving thirty seconds later.

    Duration is not the property being tested and the timeout is shortened
    here so it is not being timed: what these assert is the STATE on return -
    no announcement, no orphaned coordinator, and a raise the lifecycle
    registry can turn into a degraded `/health` and a retry that announces
    when the store is back.
    """

    async def _boot_against_a_store_that_never_subscribes(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> tuple[_NeverLiveEventStore, CoordinatorSubscriptionService]:
        from syn_adapters.subscriptions import coordinator_service
        from syn_api.services import lifecycle

        monkeypatch.setattr(coordinator_service, "_SUBSCRIPTION_OPEN_TIMEOUT_SECONDS", 0.0)
        store = _NeverLiveEventStore()
        gate = AdmissionGate(
            InMemoryMaintenanceAdapter(),
            EventStoreAdmissionAnnouncer(store),  # type: ignore[arg-type]
        )
        service = CoordinatorSubscriptionService(
            event_store=store,  # type: ignore[arg-type]
            projections=[],
            checkpoint_store=MemoryCheckpointStore(),
        )
        monkeypatch.setattr(lifecycle, "get_admission_gate", lambda: gate)
        monkeypatch.setattr(lifecycle, "get_realtime", lambda: None)
        monkeypatch.setattr(lifecycle, "get_subscription_coordinator", lambda **_kwargs: service)
        return store, service

    async def test_the_startup_fails_instead_of_announcing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from syn_api.services import lifecycle

        store, _service = await self._boot_against_a_store_that_never_subscribes(monkeypatch)
        state = lifecycle.LifecycleState()
        state.workflow_dispatcher = object()  # type: ignore[assignment]

        with pytest.raises(SubscriptionNotLiveError):
            await lifecycle._init_subscriptions(state)

        assert store.subscribed is False, "wrong bug: the coordinator did subscribe"
        assert store.appended == [], (
            "startup announced that admission was open while the coordinator "
            "was not subscribed, so the announcement is backlog to it and the "
            "trigger a deploy paused stays parked (#1387, finding B)"
        )
        assert state.subscription_service is None, (
            "a service whose start() raised was registered as the running one"
        )

    async def test_the_failed_start_leaves_no_coordinator_behind(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Failing is only half of it; the attempt has to clean up after itself.

        Nothing upstream can: `start()` raised, so the caller never got the
        service back, and the recovery loop builds a NEW one on every retry. A
        task left running here would stack another coordinator - and another
        checkpoint pool - against the same store on each pass.
        """
        from syn_api.services import lifecycle

        _store, service = await self._boot_against_a_store_that_never_subscribes(monkeypatch)
        state = lifecycle.LifecycleState()
        state.workflow_dispatcher = object()  # type: ignore[assignment]

        with pytest.raises(SubscriptionNotLiveError):
            await lifecycle._init_subscriptions(state)

        assert service.is_running is False
        task = service._subscription_task
        assert task is not None
        assert task.done(), (
            "the coordinator task outlived the start() that created it, so "
            "each recovery retry adds another one against the same store"
        )

    async def test_a_second_start_does_not_report_live_either(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`start()` has two ways out and both owe the caller the same thing.

        The early return for an already-running service is the other door into
        finding B: a caller told "started" while the first start is still in
        flight would announce into exactly the gap the wait exists to close.
        """
        _store, service = await self._boot_against_a_store_that_never_subscribes(monkeypatch)

        with pytest.raises(SubscriptionNotLiveError):
            await service.start()

        service._running = True  # the first start, still in flight

        with pytest.raises(SubscriptionNotLiveError):
            await service.start()
