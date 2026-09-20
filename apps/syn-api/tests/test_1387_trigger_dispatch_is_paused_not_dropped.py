"""A trigger refused during a deploy is recorded, not dropped (#1387).

Triggers are the admission path nobody remembers: webhooks and the two pollers
all funnel into ``TriggerFired`` and dispatch on their own schedule, with no
operator involved at all. Whatever the deploy script does, that path keeps
admitting work unless something stops it.

Two things have to be true for the refusal to be honest, and both are asserted
against the REAL bridge (``BackgroundWorkflowDispatcher``) rather than a stand-in
for it, because the bug being prevented lives in the seam: the projection awaits
``run_workflow()`` and then writes ``status="dispatched"``, so a refusal raised
inside the fire-and-forget task would leave a record claiming a run that never
happened.

1. Nothing is admitted - the handler is never reached.
2. The record says ``paused``, not ``failed`` and not ``dispatched``, and the
   record is picked up again once the gate clears. A refusal that is recorded
   and never retried is a dropped trigger with a nicer label.
"""

from __future__ import annotations

import asyncio
import os
from typing import TypedDict, cast

import pytest
from event_sourcing.core.event import EventEnvelope, EventMetadata
from event_sourcing.stores.memory_checkpoint import MemoryCheckpointStore
from event_sourcing.stores.memory_projection import MemoryProjectionStore

os.environ.setdefault("APP_ENVIRONMENT", "test")

from syn_adapters.maintenance import InMemoryMaintenanceAdapter
from syn_api._wiring import BackgroundWorkflowDispatcher
from syn_domain.contexts._shared import AdmissionGate, AdmissionTicket
from syn_domain.contexts.github.domain.events.TriggerFiredEvent import TriggerFiredEvent
from syn_domain.contexts.github.slices.dispatch_triggered_workflow.projection import (
    WorkflowDispatchProjection,
)

pytestmark = pytest.mark.unit

_PROJECTION = WorkflowDispatchProjection.PROJECTION_NAME


class _DispatchRecord(TypedDict, total=False):
    """The dispatch record these tests read, by the names they read it under.

    The store hands back an untyped mapping, so this narrows it at the one
    place the tests touch it. Named keys mean a projection that renamed a
    field breaks here rather than quietly asserting against a missing key,
    which `.get()`-style access would turn into a pass.
    """

    status: str
    status_reason: str | None
    dispatched_at: str | None


class _RecordingHandler:
    """Stands in for ExecuteWorkflowHandler. Records what was admitted."""

    def __init__(self) -> None:
        self.admitted: list[object] = []

    async def validate_stored_declarations(self, _workflow_id: str) -> None:
        return None

    async def handle(self, command: object, *, admitted: AdmissionTicket | None = None) -> None:
        self.admitted.append(command)
        # The real handler reaches `journal.open()` through the processor and
        # the lease ends there (#1387); this double stands in for that.
        if admitted is not None:
            admitted.mark_visible()


class _Fixture:
    def __init__(self) -> None:
        self.store = MemoryProjectionStore()
        self.checkpoints = MemoryCheckpointStore()
        self.handler = _RecordingHandler()
        # The real gate over the real port, because #1387's verification found
        # the defect in the gap between them: the dispatcher holding only a
        # port could read it, have the operator's set complete, and admit
        # anyway. A double for either half would hide that.
        self.maintenance = AdmissionGate(InMemoryMaintenanceAdapter())
        self.dispatcher = BackgroundWorkflowDispatcher(
            self.handler,  # type: ignore[arg-type]
            maintenance=self.maintenance,
        )
        self.projection = WorkflowDispatchProjection(
            execution_service=self.dispatcher,
            store=self.store,
        )

    async def a_trigger_fires(self, execution_id: str = "exec-abc123") -> None:
        """A real `github.TriggerFired` envelope, as any of the three sources
        produces it: webhook, Events API poller, or Checks API poller. They
        converge here, so gating this covers all three."""
        event = TriggerFiredEvent(
            trigger_id="trg-ci-self-healing",
            execution_id=execution_id,
            workflow_id="wf-ci-self-healing",
            workflow_inputs={"repository": "syntropic137/syntropic137"},
            github_event_type="check_run.completed",
        )
        envelope = EventEnvelope(
            event=event,
            metadata=EventMetadata(
                event_type=TriggerFiredEvent.event_type,
                aggregate_id="trg-ci-self-healing",
                aggregate_type="TriggerRule",
                aggregate_nonce=1,
                global_nonce=1,
            ),
        )
        await self.projection.handle_event(envelope, self.checkpoints)

    async def record(self, execution_id: str = "exec-abc123") -> _DispatchRecord:
        found = await self.store.get(_PROJECTION, execution_id)
        assert found is not None, "the trigger produced no dispatch record at all"
        return cast("_DispatchRecord", found)

    async def drain_the_dispatcher(self) -> None:
        """Wait for the fire-and-forget tasks instead of cancelling them.

        `shutdown()` cancels, which is right at process exit and wrong here -
        it would hide whether the handler was ever reached.
        """
        while self.dispatcher._tasks:
            await asyncio.gather(*self.dispatcher._tasks)


@pytest.fixture
async def fixture() -> _Fixture:
    return _Fixture()


class TestATriggerThatFiresWhileAdmissionIsPaused:
    async def test_admits_nothing(self, fixture: _Fixture) -> None:
        await fixture.a_trigger_fires()
        await fixture.maintenance.set_mode(active=True, reason="pit stop", actor="deploy")

        await fixture.projection.process_pending()
        await fixture.drain_the_dispatcher()

        assert fixture.handler.admitted == [], (
            "the trigger reached the execution handler while admission was paused"
        )

    async def test_is_recorded_as_paused_rather_than_failed(self, fixture: _Fixture) -> None:
        """`failed` would say the dispatch was attempted and went wrong."""
        await fixture.a_trigger_fires()
        await fixture.maintenance.set_mode(active=True, reason="pit stop", actor="deploy")

        await fixture.projection.process_pending()

        record = await fixture.record()
        assert record["status"] == "paused"
        assert record["status_reason"] == "maintenance_mode"

    async def test_is_not_recorded_as_dispatched(self, fixture: _Fixture) -> None:
        """The #1039 failure mode: a record claiming a run that never happened."""
        await fixture.a_trigger_fires()
        await fixture.maintenance.set_mode(active=True, reason="pit stop", actor="deploy")

        await fixture.projection.process_pending()

        record = await fixture.record()
        assert record["status"] != "dispatched"
        assert record["dispatched_at"] is None

    async def test_is_dispatched_once_the_gate_clears(self, fixture: _Fixture) -> None:
        """The whole point of `paused` over `failed`: the work is still owed."""
        await fixture.a_trigger_fires()
        await fixture.maintenance.set_mode(active=True, reason="pit stop", actor="deploy")
        await fixture.projection.process_pending()

        await fixture.maintenance.set_mode(active=False, reason="", actor="deploy")
        await fixture.projection.process_pending()
        await fixture.drain_the_dispatcher()

        record = await fixture.record()
        assert record["status"] == "dispatched"
        assert len(fixture.handler.admitted) == 1


class TestTheSameTriggerWithTheGateOpen:
    """The negative control. Without it, a projection that dispatched nothing
    at all would pass every assertion above."""

    async def test_is_dispatched(self, fixture: _Fixture) -> None:
        await fixture.a_trigger_fires()

        await fixture.projection.process_pending()
        await fixture.drain_the_dispatcher()

        record = await fixture.record()
        assert record["status"] == "dispatched"
        assert len(fixture.handler.admitted) == 1
