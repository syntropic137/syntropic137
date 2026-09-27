"""An admitted fork's child is started through the gate, and says how it went.

The same seam as #1387's trigger path, and the same hazard (#1039): the
process manager awaits `start_fork()` and then writes a status, so a refusal
raised inside the fire-and-forget task would leave a record claiming a child
that never started. So these run the REAL process manager over the REAL
dispatcher and gate; only `StartForkHandler` is a double, because what it does
once admitted is proven in the domain against the real processor.
"""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from event_sourcing.core.event import EventEnvelope, EventMetadata
from event_sourcing.stores.memory_checkpoint import MemoryCheckpointStore
from event_sourcing.stores.memory_projection import MemoryProjectionStore

if TYPE_CHECKING:
    from event_sourcing import DomainEvent

os.environ.setdefault("APP_ENVIRONMENT", "test")

from syn_adapters.maintenance import InMemoryMaintenanceAdapter
from syn_api._wiring_admission import BackgroundWorkflowDispatcher
from syn_domain.contexts._shared import AdmissionGate, AdmissionTicket
from syn_domain.contexts._shared.integration_events.AdmissionOpenEvent import (
    AdmissionOpenEvent,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    InheritedPhase,
)
from syn_domain.contexts.orchestration.domain.events.ExecutionForkedEvent import (
    ExecutionForkedEvent,
)
from syn_domain.contexts.orchestration.slices.start_fork import (
    ForkStartProcessManager,
    ForkStartRecord,
)

pytestmark = pytest.mark.unit

PARENT = "exec-parent-1454"
_PROJECTION = ForkStartProcessManager.PROJECTION_NAME


class _ForkHandler:
    """Stands in for StartForkHandler: refuses on request, records what it started."""

    def __init__(self) -> None:
        self.refusal: str | None = None
        self.started: list[str] = []

    async def validate(self, parent_execution_id: str) -> None:
        del parent_execution_id
        if self.refusal is not None:
            raise ValueError(self.refusal)

    async def handle(
        self, parent_execution_id: str, *, admitted: AdmissionTicket | None = None
    ) -> None:
        self.started.append(parent_execution_id)
        if admitted is not None:
            admitted.mark_visible()


class _Fixture:
    def __init__(self) -> None:
        self.store = MemoryProjectionStore()
        self.checkpoints = MemoryCheckpointStore()
        self.forks = _ForkHandler()
        self.maintenance = AdmissionGate(InMemoryMaintenanceAdapter())
        self.dispatcher = BackgroundWorkflowDispatcher(
            handler=None,  # type: ignore[arg-type]  # the fork path never reaches it
            maintenance=self.maintenance,
            fork_handler=self.forks,  # type: ignore[arg-type]
        )
        self.manager = ForkStartProcessManager(fork_starter=self.dispatcher, store=self.store)
        self._nonce = 0

    async def _deliver(self, event: DomainEvent, event_type: str, aggregate_id: str) -> None:
        self._nonce += 1
        envelope = EventEnvelope(
            event=event,
            metadata=EventMetadata(
                event_type=event_type,
                aggregate_id=aggregate_id,
                aggregate_type="WorkflowExecution",
                aggregate_nonce=self._nonce,
                global_nonce=self._nonce,
            ),
        )
        await self.manager.handle_event(envelope, self.checkpoints)

    async def the_parent_forks(self) -> None:
        event = ExecutionForkedEvent(
            workflow_id="wf-1",
            execution_id=PARENT,
            fork_execution_id="exec-child-1454",
            inherited_phases=[InheritedPhase(phase_id="research", artifact_ids=["art-1"])],
            resume_phase_id="plan",
            forked_at=datetime.now(UTC),
        )
        await self._deliver(event, "ExecutionForked", PARENT)

    async def admission_reopens(self) -> None:
        await self._deliver(
            AdmissionOpenEvent(announced_at=datetime.now(UTC), actor="deploy"),
            AdmissionOpenEvent.event_type,
            "maintenance",
        )

    async def record(self) -> ForkStartRecord:
        row = await self.store.get(_PROJECTION, PARENT)
        assert row is not None, "the fork produced no start record at all"
        return ForkStartRecord.model_validate(row)

    async def drain(self) -> None:
        while self.dispatcher._tasks:  # pyright: ignore[reportPrivateUsage]
            await asyncio.gather(*self.dispatcher._tasks)  # pyright: ignore[reportPrivateUsage]


@pytest.fixture
async def fixture() -> _Fixture:
    return _Fixture()


class TestAnAdmittedFork:
    async def test_is_owed_a_start_before_anything_runs(self, fixture: _Fixture) -> None:
        await fixture.the_parent_forks()

        assert (await fixture.record()).status == "pending"
        assert fixture.forks.started == []

    async def test_is_started_once_processed(self, fixture: _Fixture) -> None:
        await fixture.the_parent_forks()

        assert await fixture.manager.process_pending() == 1
        await fixture.drain()

        assert (await fixture.record()).status == "started"
        assert fixture.forks.started == [PARENT]

    async def test_a_replayed_fork_does_not_reopen_a_started_record(
        self, fixture: _Fixture
    ) -> None:
        await fixture.the_parent_forks()
        await fixture.manager.process_pending()
        await fixture.drain()

        await fixture.the_parent_forks()
        await fixture.manager.process_pending()
        await fixture.drain()

        assert (await fixture.record()).status == "started"
        assert fixture.forks.started == [PARENT]


class TestAForkStartedWhileAdmissionIsPaused:
    async def test_starts_nothing_and_is_recorded_paused(self, fixture: _Fixture) -> None:
        await fixture.the_parent_forks()
        await fixture.maintenance.set_mode(active=True, reason="pit stop", actor="deploy")

        assert await fixture.manager.process_pending() == 0
        await fixture.drain()

        assert (await fixture.record()).status == "paused"
        assert fixture.forks.started == []

    async def test_is_started_once_admission_reopens(self, fixture: _Fixture) -> None:
        await fixture.the_parent_forks()
        await fixture.maintenance.set_mode(active=True, reason="pit stop", actor="deploy")
        await fixture.manager.process_pending()

        await fixture.maintenance.set_mode(active=False, reason="", actor="deploy")
        await fixture.admission_reopens()
        await fixture.manager.process_pending()
        await fixture.drain()

        assert (await fixture.record()).status == "started"
        assert fixture.forks.started == [PARENT]


class TestAForkTheChildRefuses:
    async def test_is_recorded_failed_with_the_reason_not_started(self, fixture: _Fixture) -> None:
        """#1039: the refusal must reach the record, not die in a background task."""
        fixture.forks.refusal = "Cannot start fork exec-child-1454: no pinned phase config"
        await fixture.the_parent_forks()

        await fixture.manager.process_pending()
        await fixture.drain()

        record = await fixture.record()
        assert record.status == "failed"
        assert record.status_reason == fixture.forks.refusal
        assert fixture.forks.started == []

    async def test_is_not_retried(self, fixture: _Fixture) -> None:
        fixture.forks.refusal = "refused"
        await fixture.the_parent_forks()
        await fixture.manager.process_pending()

        fixture.forks.refusal = None
        assert await fixture.manager.process_pending() == 0
        assert fixture.forks.started == []
