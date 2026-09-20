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
from typing import TYPE_CHECKING

import pytest
from event_sourcing import DomainEvent, EventEnvelope, EventMetadata
from event_sourcing.stores.memory_checkpoint import MemoryCheckpointStore
from event_sourcing.stores.memory_projection import MemoryProjectionStore
from event_sourcing.subscriptions.coordinator import SubscriptionCoordinator

os.environ.setdefault("APP_ENVIRONMENT", "test")

from syn_adapters.maintenance import EventStoreAdmissionAnnouncer, InMemoryMaintenanceAdapter
from syn_api._wiring import BackgroundWorkflowDispatcher
from syn_domain.contexts._shared import AdmissionGate, AdmissionTicket
from syn_domain.contexts.github._shared.projection_names import WORKFLOW_DISPATCH
from syn_domain.contexts.github.domain.events.TriggerFiredEvent import TriggerFiredEvent
from syn_domain.contexts.github.slices.dispatch_triggered_workflow.projection import (
    WorkflowDispatchProjection,
)

if TYPE_CHECKING:
    from event_sourcing import ProjectionStore

pytestmark = pytest.mark.unit

_PATIENCE = 5.0
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

    def subscribes(self, coordinator: SubscriptionCoordinator) -> None:
        self._coordinator = coordinator

    async def append_events(
        self,
        stream_name: str,
        events: list[EventEnvelope[DomainEvent]],
        expected_version: int | None = None,
    ) -> None:
        del stream_name, expected_version
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
        # Past the boundary: this process has caught up, so ProcessManagers
        # are allowed to run their processor side. Exactly the state a real
        # coordinator reaches after replay.
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
