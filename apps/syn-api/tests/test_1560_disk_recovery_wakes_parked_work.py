"""Freeing disk space wakes the work a full disk parked (#1560).

A trigger or resume refused below the free-space floor is saved as ``paused``,
and both ProcessManagers re-offer ``paused`` records - but only when the
coordinator runs their processor side, which it does after a live SUBSCRIBED
event and nowhere else. Space coming back is not an event. Without a wake-up
the record stays parked until some unrelated trigger arrives, which on a quiet
system is never: a held trigger becomes a dropped one with a nicer label.

The wake-up is the same announcement that clearing maintenance mode writes,
asked for by a clock (`announce_when_disk_recovers`) and decided by the gate.
These tests run the REAL `SubscriptionCoordinator` over the REAL trigger
dispatch projection and resume process manager, and the REAL clock. Nothing
here calls `process_pending()`; nothing here delivers a second trigger.
"""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime

import pytest
from event_sourcing import DomainEvent, EventEnvelope, EventMetadata
from event_sourcing.stores.memory_checkpoint import MemoryCheckpointStore
from event_sourcing.subscriptions.coordinator import SubscriptionCoordinator

os.environ.setdefault("APP_ENVIRONMENT", "test")

from syn_adapters.maintenance import EventStoreAdmissionAnnouncer, InMemoryMaintenanceAdapter
from syn_adapters.projection_stores.memory_store import InMemoryProjectionStore
from syn_api._wiring_admission import BackgroundWorkflowDispatcher
from syn_api.services import admission_announcement
from syn_domain.contexts._shared import AdmissionGate, AdmissionTicket
from syn_domain.contexts._shared.disk_space import DiskSpaceGuard, DiskUsage
from syn_domain.contexts.github.domain.events.TriggerFiredEvent import TriggerFiredEvent
from syn_domain.contexts.github.slices.dispatch_triggered_workflow.projection import (
    WorkflowDispatchProjection,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    InheritedPhase,
)
from syn_domain.contexts.orchestration.domain.events.ExecutionResumedEvent import (
    ExecutionResumedEvent,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.processor_types import (
    WorkflowExecutionResult,
)
from syn_domain.contexts.orchestration.slices.start_resume import (
    ResumeChild,
    ResumeStartProcessManager,
)

pytestmark = pytest.mark.unit

_EXECUTION = "exec-disk-recovery-1560"
_PARENT = "exec-parent-disk-1560"
_GIB = 2**30
_PATIENCE = 5.0
_ADMISSION_OPEN = "maintenance.AdmissionOpen"


class _MutableDisk:
    """`DiskSpacePort` double whose free space the test changes."""

    def __init__(self, free_percent: float) -> None:
        self.free_percent = free_percent

    @property
    def path(self) -> str:
        return "/workspaces"

    def usage(self) -> DiskUsage:
        total = 100 * _GIB
        return DiskUsage(free_bytes=int(total * self.free_percent / 100), total_bytes=total)


class _LiveEventStore:
    """Appends are delivered to the coordinator as live events, as production's are."""

    def __init__(self) -> None:
        self.appended: list[EventEnvelope[DomainEvent]] = []
        self.coordinator: SubscriptionCoordinator | None = None
        self._nonce = 100

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

    async def deliver(self, event: DomainEvent, metadata: EventMetadata) -> None:
        assert self.coordinator is not None
        self._nonce += 1
        await self.coordinator.dispatch_event(
            EventEnvelope(
                event=event, metadata=metadata.model_copy(update={"global_nonce": self._nonce})
            )
        )
        await self.coordinator.wait_for_process_managers()


class _Handlers:
    """Both execution handlers, reduced to "it was reached and became durable"."""

    def __init__(self) -> None:
        self.executions: list[str] = []
        self.resumes: list[str] = []

    async def validate_stored_declarations(self, _workflow_id: str) -> None:
        return None

    async def handle(
        self, command: object, *, admitted: AdmissionTicket | None = None
    ) -> WorkflowExecutionResult:
        self.executions.append(getattr(command, "execution_id", "") or "")
        if admitted is not None:
            admitted.mark_visible()
        # The dispatcher reads the result it is given (#1547).
        return WorkflowExecutionResult(
            workflow_id="wf",
            execution_id=getattr(command, "execution_id", "") or "",
            status="completed",
            started_at=datetime(2026, 10, 5, tzinfo=UTC),
        )

    async def validate(self, _parent_execution_id: str) -> None:
        return None


class _ResumeHandler:
    def __init__(self, handlers: _Handlers) -> None:
        self._handlers = handlers

    async def validate(self, _parent_execution_id: str) -> ResumeChild:
        # #1557: validate names the child, so its start queues under that id.
        return ResumeChild(execution_id="exec-child-disk-1560", workflow_id="wf")

    async def handle(
        self, parent_execution_id: str, *, admitted: AdmissionTicket | None = None
    ) -> None:
        if parent_execution_id not in self._handlers.resumes:
            self._handlers.resumes.append(parent_execution_id)
        if admitted is not None:
            admitted.mark_visible()


class _Api:
    """One API process: gate over a measurable disk, both ProcessManagers, one coordinator."""

    def __init__(self) -> None:
        self.disk = _MutableDisk(free_percent=3.0)
        self.events = _LiveEventStore()
        self.port = InMemoryMaintenanceAdapter()
        self.gate = AdmissionGate(
            self.port,
            EventStoreAdmissionAnnouncer(self.events),  # type: ignore[arg-type]
            DiskSpaceGuard(self.disk, degraded_below_percent=10, refuse_admission_below_percent=5),
        )
        self.handlers = _Handlers()
        self.dispatcher = BackgroundWorkflowDispatcher(
            self.handlers,  # type: ignore[arg-type]
            maintenance=self.gate,
            resume_handler=_ResumeHandler(self.handlers),  # type: ignore[arg-type]
        )
        self.store = InMemoryProjectionStore()
        self.coordinator = SubscriptionCoordinator(
            event_store=self.events,  # type: ignore[arg-type]
            checkpoint_store=MemoryCheckpointStore(),
            projections=[
                WorkflowDispatchProjection(execution_service=self.dispatcher, store=self.store),
                ResumeStartProcessManager(resume_starter=self.dispatcher, store=self.store),
            ],
        )
        # Already live, as a real coordinator is after replay: these tests are
        # about what happens to a LIVE process once the disk recovers.
        self.coordinator.live_boundary_nonce = 0
        self.coordinator.is_catching_up = False
        self.events.coordinator = self.coordinator

    async def a_trigger_fires(self) -> None:
        await self.events.deliver(
            TriggerFiredEvent(
                trigger_id="trigger-disk-1560",
                execution_id=_EXECUTION,
                workflow_id="wf-ci-self-healing",
                workflow_inputs={"repository": "syntropic137/syntropic137"},
                github_event_type="check_run.completed",
            ),
            EventMetadata(
                event_type="github.TriggerFired",
                aggregate_id="trigger-disk-1560",
                aggregate_type="TriggerRule",
                aggregate_nonce=1,
            ),
        )

    async def a_parent_resumes(self) -> None:
        await self.events.deliver(
            ExecutionResumedEvent(
                workflow_id="wf-1",
                execution_id=_PARENT,
                resume_execution_id="exec-child-disk-1560",
                inherited_phases=[InheritedPhase(phase_id="research", artifact_ids=["art-1"])],
                resume_phase_id="plan",
                resumed_at=datetime.now(UTC),
            ),
            EventMetadata(
                event_type="ExecutionResumed",
                aggregate_id=_PARENT,
                aggregate_type="WorkflowExecution",
                aggregate_nonce=1,
            ),
        )

    async def status(self, projection: str, key: str) -> tuple[str, str | None]:
        row = await self.store.get(projection, key)
        assert row is not None, f"no {projection} record for {key}"
        return str(row.get("status", "")), row.get("status_reason")

    async def trigger(self) -> tuple[str, str | None]:
        return await self.status(WorkflowDispatchProjection.PROJECTION_NAME, _EXECUTION)

    async def resume(self) -> tuple[str, str | None]:
        return await self.status(ResumeStartProcessManager.PROJECTION_NAME, _PARENT)

    def announcements(self) -> int:
        return sum(1 for e in self.events.appended if e.metadata.event_type == _ADMISSION_OPEN)

    async def settle(self) -> None:
        async with asyncio.timeout(_PATIENCE):
            while self.dispatcher._tasks:  # pyright: ignore[reportPrivateUsage]
                await asyncio.gather(*self.dispatcher._tasks, return_exceptions=True)  # pyright: ignore[reportPrivateUsage]
                await asyncio.sleep(0)


async def _both_parked_by_a_full_disk(api: _Api) -> None:
    await api.a_trigger_fires()
    await api.a_parent_resumes()
    assert await api.trigger() == ("paused", "insufficient_disk_space")
    assert (await api.resume())[0] == "paused"
    assert api.handlers.executions == []
    assert api.handlers.resumes == []


async def _run_the_clock_until(api: _Api, done: object, monkeypatch: pytest.MonkeyPatch) -> None:
    """Run the production clock against this API's gate, and stop it."""
    monkeypatch.setattr(admission_announcement, "get_admission_gate", lambda: api.gate)
    task = asyncio.create_task(admission_announcement.announce_when_disk_recovers(0.01))
    try:
        async with asyncio.timeout(_PATIENCE):
            while not await done():  # type: ignore[operator]
                await asyncio.sleep(0.01)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.fixture
async def api() -> _Api:
    return _Api()


class TestFreeingSpace:
    async def test_dispatches_the_parked_trigger_and_resume(
        self, api: _Api, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        await _both_parked_by_a_full_disk(api)

        api.disk.free_percent = 50.0

        async def both_ran() -> bool:
            await api.settle()
            return api.handlers.executions == [_EXECUTION] and api.handlers.resumes == [_PARENT]

        await _run_the_clock_until(api, both_ran, monkeypatch)
        assert (await api.trigger())[0] == "dispatched"
        assert (await api.resume())[0] == "dispatched"
        assert api.announcements() == 1
        assert await api.gate.announce_if_disk_recovered() is False, (
            "one recovery, one announcement - not one per tick"
        )
        assert api.announcements() == 1


class TestNoFalseWake:
    async def test_a_still_full_disk_announces_nothing(
        self, api: _Api, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        await _both_parked_by_a_full_disk(api)
        ticks = 0

        async def a_few_ticks() -> bool:
            nonlocal ticks
            ticks += 1
            return ticks > 10

        await _run_the_clock_until(api, a_few_ticks, monkeypatch)
        assert api.announcements() == 0
        assert await api.trigger() == ("paused", "insufficient_disk_space")

    async def test_a_disk_that_never_refused_announces_nothing(self, api: _Api) -> None:
        api.disk.free_percent = 50.0
        assert await api.gate.announce_if_disk_recovered() is False
        assert api.announcements() == 0

    async def test_maintenance_mode_holds_the_wake_for_its_own_clear(self, api: _Api) -> None:
        """Announcing into a shut gate would re-park everything it woke.
        Clearing maintenance announces anyway."""
        await _both_parked_by_a_full_disk(api)
        await api.gate.set_mode(active=True, reason="pit stop", actor="deploy")
        api.disk.free_percent = 50.0

        assert await api.gate.announce_if_disk_recovered() is False
        assert api.announcements() == 0
