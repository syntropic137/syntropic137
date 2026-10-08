"""#1707: a trigger queued for an execution slot survives a restart.

The dispatcher takes a trigger's start and queues it in process memory until a
slot frees. The trigger record used to say `dispatched` from that moment, and
`dispatched` is never re-offered, so a start still queued when the process was
stopped - every deploy - or crashed was lost: nothing ran it, and nothing would.

The record now says `queued` until the dispatcher confirms the execution is
durable. A `queued` record is re-offered by a process that does not hold the
start, and a re-offer of a start that did become durable is refused by the
execution stream and settled, not run twice.

Real gate, budget, dispatcher and projection; the two "processes" share only
what survives a restart - the projection store and the execution streams. The
handler is the double, because what it does once admitted is proven against
the real processor elsewhere.
"""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime

import pytest
from event_sourcing.core.event import EventEnvelope, EventMetadata
from event_sourcing.stores.memory_checkpoint import MemoryCheckpointStore

from syn_adapters.projection_stores.memory_store import InMemoryProjectionStore

os.environ.setdefault("APP_ENVIRONMENT", "test")

from syn_adapters.maintenance import InMemoryMaintenanceAdapter
from syn_api._wiring_admission import BackgroundWorkflowDispatcher
from syn_api.execution_budget import ExecutionBudget
from syn_domain.contexts._shared import AdmissionGate, AdmissionTicket
from syn_domain.contexts.github.domain.events.TriggerFiredEvent import TriggerFiredEvent
from syn_domain.contexts.github.slices.dispatch_triggered_workflow.projection import (
    WorkflowDispatchProjection,
)
from syn_domain.contexts.orchestration import DuplicateExecutionError
from syn_domain.contexts.orchestration.slices.execute_workflow.processor_types import (
    WorkflowExecutionResult,
)

pytestmark = pytest.mark.unit

_PATIENCE = 5.0
_TRIGGERED = "exec-trigger-1707"


class _Streams:
    """The execution streams: what the event store keeps across a restart."""

    def __init__(self) -> None:
        self.opened: list[str] = []


class _Handler:
    """Opens the execution's stream - NoStream, so a second open is refused -
    reports the write the way the processor does, then runs until told to
    finish, the way a real execution holds its slot.

    ``reports=False`` is a process that dies between the write and the report:
    the stream exists and nobody was told. The real processor's report is
    proven in test_1707_a_trigger_is_dispatched_at_its_durable_write.
    """

    def __init__(self, streams: _Streams, *, fails: bool = False, reports: bool = True) -> None:
        self._streams = streams
        self._fails = fails
        self._reports = reports
        self.may_finish = asyncio.Event()

    async def validate_stored_declarations(self, _workflow_id: str) -> None:
        return None

    async def handle(
        self, command: object, *, admitted: AdmissionTicket | None = None
    ) -> WorkflowExecutionResult:
        execution_id = getattr(command, "execution_id", "") or ""
        if self._fails:
            msg = "the template could not be read"
            raise RuntimeError(msg)
        if execution_id in self._streams.opened:
            raise DuplicateExecutionError(execution_id)
        self._streams.opened.append(execution_id)
        if admitted is not None and self._reports:
            await admitted.mark_durable()
        await self.may_finish.wait()
        return WorkflowExecutionResult(
            workflow_id="wf",
            execution_id=execution_id,
            status="completed",
            started_at=datetime(2026, 10, 8, tzinfo=UTC),
        )


class _Process:
    """One API process: its own gate, budget and dispatcher, the shared store."""

    def __init__(self, store: InMemoryProjectionStore, streams: _Streams, **handler: bool) -> None:
        self.handler = _Handler(streams, **handler)
        self.dispatcher = BackgroundWorkflowDispatcher(
            self.handler,  # type: ignore[arg-type]
            maintenance=AdmissionGate(InMemoryMaintenanceAdapter()),
            budget=ExecutionBudget(1),
        )
        self.projection = WorkflowDispatchProjection(
            execution_service=self.dispatcher,  # type: ignore[arg-type]
            store=store,
        )
        self._store = store

    async def a_trigger_fires(self) -> None:
        event = TriggerFiredEvent(
            trigger_id="trg-1707",
            execution_id=_TRIGGERED,
            workflow_id="wf",
            workflow_inputs={},
            github_event_type="check_run.completed",
        )
        envelope = EventEnvelope(
            event=event,
            metadata=EventMetadata(
                event_type=TriggerFiredEvent.event_type,
                aggregate_id="trg-1707",
                aggregate_type="TriggerRule",
                aggregate_nonce=1,
                global_nonce=1,
            ),
        )
        await self.projection.handle_event(envelope, MemoryCheckpointStore())

    async def status(self) -> tuple[str, str | None]:
        found = await self._store.get(WorkflowDispatchProjection.PROJECTION_NAME, _TRIGGERED)
        assert found is not None, "the trigger produced no dispatch record at all"
        reason = found.get("status_reason")
        return str(found.get("status")), None if reason is None else str(reason)

    async def settle(self) -> None:
        for _ in range(20):
            await asyncio.sleep(0)

    async def finish(self) -> None:
        self.handler.may_finish.set()
        async with asyncio.timeout(_PATIENCE):
            while self.dispatcher._tasks:  # pyright: ignore[reportPrivateUsage]
                await asyncio.gather(*self.dispatcher._tasks)  # pyright: ignore[reportPrivateUsage]
                await asyncio.sleep(0)


class TestATriggerQueuedWhenTheProcessStops:
    async def test_is_started_by_the_next_process(self) -> None:
        store, streams = InMemoryProjectionStore(), _Streams()
        before = _Process(store, streams)
        await before.dispatcher.run_workflow("wf", {}, "exec-busy")
        await before.settle()
        await before.a_trigger_fires()

        assert await before.projection.process_pending() == 1
        assert before.dispatcher.budget.waiting == 1, "the trigger should wait for a slot"
        assert (await before.status())[0] == "queued", (
            "the record says the start happened while it is only in this process's queue"
        )
        assert await before.projection.process_pending() == 0, (
            "a start this process still holds was offered again"
        )

        await before.dispatcher.shutdown()  # the deploy's swap

        after = _Process(store, streams)
        assert await after.projection.process_pending() == 1, "the queued trigger was lost"
        await after.settle()
        assert streams.opened == ["exec-busy", _TRIGGERED]
        await after.finish()
        assert await after.status() == ("dispatched", None)
        assert await after.projection.process_pending() == 0


class TestATriggerWhoseExecutionBecameDurableBeforeTheCrash:
    async def test_is_dispatched_while_it_runs(self) -> None:
        store, streams = InMemoryProjectionStore(), _Streams()
        process = _Process(store, streams)
        await process.a_trigger_fires()
        await process.projection.process_pending()
        await process.settle()
        assert streams.opened == [_TRIGGERED]

        assert await process.status() == ("dispatched", None), (
            "the execution is durable and running, and the record still says it may not exist"
        )
        await process.finish()

    async def test_is_settled_and_not_run_twice(self) -> None:
        store, streams = InMemoryProjectionStore(), _Streams()
        before = _Process(store, streams, reports=False)
        await before.a_trigger_fires()
        await before.projection.process_pending()
        await before.settle()
        assert streams.opened == [_TRIGGERED]

        await before.dispatcher.shutdown()  # between the write and its report
        assert (await before.status())[0] == "queued"

        after = _Process(store, streams)
        assert await after.projection.process_pending() == 1
        await after.finish()
        assert streams.opened == [_TRIGGERED], "the execution was started twice"
        assert await after.status() == ("dispatched", None)
        assert await after.projection.process_pending() == 0


class TestATriggerWhoseStartFailsBeforeItsExecutionExists:
    async def test_is_failed_and_not_offered_again(self) -> None:
        store, streams = InMemoryProjectionStore(), _Streams()
        process = _Process(store, streams, fails=True)
        await process.a_trigger_fires()
        await process.projection.process_pending()
        await process.finish()

        assert await process.status() == ("failed", "start_exception")
        assert await process.projection.process_pending() == 0
        assert streams.opened == []
