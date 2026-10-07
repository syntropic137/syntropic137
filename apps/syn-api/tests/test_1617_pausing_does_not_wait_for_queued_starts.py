"""Pausing admission returns promptly however deep the queue is (#1617).

Seen on the beta.12 pit stop: four executions running, six queued, and
``PUT /maintenance {"active": true}`` timed out twice. The pause waited for
every admitted start to write its start event, and a queued start cannot do
that until a running execution finishes and frees its slot.

The rule these tests pin, through the real dispatcher, budget and gate:

* a start QUEUED for a slot does not hold the pause; when its slot comes it
  re-checks the gate and, paused, does not start - it is handed back as held
  so its durable record offers it again after the re-open;
* a start that HOLDS a slot and has not written its start event still holds
  the pause (#1387), for a bound;
* the queued starts survive a restart and start after the re-open.

Triggers and resumes go through different callers (#1677), so both are here.
Only the handlers are doubles, because what they do once admitted is proven
against the real processor elsewhere.
"""

from __future__ import annotations

import asyncio
import importlib
import os
from datetime import UTC, datetime, timedelta

import pytest
from event_sourcing.core.event import EventEnvelope, EventMetadata
from event_sourcing.stores.memory_checkpoint import MemoryCheckpointStore

from syn_adapters.projection_stores.memory_store import InMemoryProjectionStore

os.environ.setdefault("APP_ENVIRONMENT", "test")

from syn_adapters.maintenance import InMemoryMaintenanceAdapter
from syn_api._wiring_admission import BackgroundWorkflowDispatcher
from syn_api.execution_budget import ExecutionBudget
from syn_domain.contexts._shared import AdmissionGate, AdmissionTicket
from syn_domain.contexts._shared.integration_events.AdmissionOpenEvent import (
    AdmissionOpenEvent,
)
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
    ResumeStartRecord,
)

pytestmark = pytest.mark.unit

#: Long enough that a loaded machine never trips it; a pause that waits on the
#: queue never returns at all, so this is far above "promptly".
_PATIENCE = 5.0

_start_todo = importlib.import_module("syn_domain.contexts.orchestration._shared.start_todo")


async def _let_the_loop_run() -> None:
    for _ in range(20):
        await asyncio.sleep(0)


class _LongRunningHandler:
    """Writes its start event at once - the execution is visible - and then
    runs until told to finish, the way a real execution holds its slot."""

    def __init__(self) -> None:
        self.started: list[str] = []
        self.may_finish = asyncio.Event()

    async def validate_stored_declarations(self, _workflow_id: str) -> None:
        return None

    async def handle(
        self, command: object, *, admitted: AdmissionTicket | None = None
    ) -> WorkflowExecutionResult:
        execution_id = getattr(command, "execution_id", "") or ""
        self.started.append(execution_id)
        if admitted is not None:
            admitted.mark_visible()
        await self.may_finish.wait()
        return WorkflowExecutionResult(
            workflow_id="wf",
            execution_id=execution_id,
            status="completed",
            started_at=datetime(2026, 10, 7, tzinfo=UTC),
        )


async def _drain(dispatcher: BackgroundWorkflowDispatcher) -> None:
    while dispatcher._tasks:  # pyright: ignore[reportPrivateUsage]
        await asyncio.gather(*dispatcher._tasks)  # pyright: ignore[reportPrivateUsage]
        # A gather over tasks already done completes without yielding, so the
        # done callbacks that discard them would never run and this would spin.
        await asyncio.sleep(0)


class TestSixTriggersQueuedBehindFourRunning:
    async def test_the_pause_returns_and_the_queue_starts_after_the_reopen(self) -> None:
        gate = AdmissionGate(InMemoryMaintenanceAdapter())
        handler = _LongRunningHandler()
        dispatcher = BackgroundWorkflowDispatcher(
            handler,  # type: ignore[arg-type]
            maintenance=gate,
            budget=ExecutionBudget(4),
        )
        held: list[str] = []

        def _holder(execution_id: str):
            async def _held(exc: Exception) -> None:
                del exc
                held.append(execution_id)

            return _held

        running = [f"exec-run-{i}" for i in range(4)]
        queued = [f"exec-queued-{i}" for i in range(6)]
        for execution_id in running:
            await dispatcher.run_workflow("wf", {}, execution_id)
        for execution_id in queued:
            await dispatcher.run_workflow("wf", {}, execution_id, on_held=_holder(execution_id))
        await _let_the_loop_run()
        assert sorted(handler.started) == sorted(running)
        assert dispatcher.budget.waiting == 6

        async with asyncio.timeout(_PATIENCE):
            mode = await gate.set_mode(active=True, reason="pit stop", actor="deploy")
        assert mode.active is True, "the pause did not return over a queue of six (#1617)"
        assert dispatcher.budget.waiting == 6, "the pause disturbed the queue"

        # The running four finish. Each freed slot goes to a queued start,
        # which finds the gate shut and is handed back held - not started.
        handler.may_finish.set()
        async with asyncio.timeout(_PATIENCE):
            await _drain(dispatcher)
        assert sorted(handler.started) == sorted(running), "a queued start ran behind the pause"
        assert sorted(held) == sorted(queued), (
            "a queued start was neither started nor held: its record would say "
            "dispatched over a start that never runs"
        )

        # The re-open: each held record offers its start again, and all run.
        await gate.set_mode(active=False, reason="", actor="deploy")
        for execution_id in queued:
            await dispatcher.run_workflow("wf", {}, execution_id)
        async with asyncio.timeout(_PATIENCE):
            await _drain(dispatcher)
        assert sorted(handler.started) == sorted(running + queued)

    async def test_a_start_holding_its_slot_still_holds_the_pause(self) -> None:
        """#1387, kept: admitted, slot held, start event not yet written."""
        gate = AdmissionGate(InMemoryMaintenanceAdapter())
        may_write = asyncio.Event()
        reached = asyncio.Event()
        recorded: list[str] = []

        class _SlowStart(_LongRunningHandler):
            async def handle(
                self, command: object, *, admitted: AdmissionTicket | None = None
            ) -> WorkflowExecutionResult:
                reached.set()
                await may_write.wait()
                recorded.append(getattr(command, "execution_id", ""))
                return await super().handle(command, admitted=admitted)

        handler = _SlowStart()
        handler.may_finish.set()
        dispatcher = BackgroundWorkflowDispatcher(
            handler,  # type: ignore[arg-type]
            maintenance=gate,
            budget=ExecutionBudget(4),
        )
        await dispatcher.run_workflow("wf", {}, "exec-in-flight")
        async with asyncio.timeout(_PATIENCE):
            await reached.wait()

        closing = asyncio.create_task(gate.set_mode(active=True, reason="pit stop", actor="deploy"))
        await _let_the_loop_run()
        assert not closing.done(), "the pause returned over an invisible, admitted start"

        may_write.set()
        async with asyncio.timeout(_PATIENCE):
            await closing
            await _drain(dispatcher)
        assert recorded == ["exec-in-flight"]


class _SlowDispatchedSave(InMemoryProjectionStore):
    """A store whose `dispatched` write for one key suspends until released -
    an async Postgres save waiting on its pool, in the shape that matters."""

    def __init__(self, key: str) -> None:
        super().__init__()
        self._key = key
        self.suspended = asyncio.Event()
        self.release = asyncio.Event()

    async def save(
        self, projection: str, key: str, data: dict[str, str | int | float | bool | None]
    ) -> None:
        if key == self._key and data.get("status") == "dispatched":
            self.suspended.set()
            await self.release.wait()
        await super().save(projection, key, data)


class TestATriggerHeldAtItsSlotWhileItsDispatchedWriteIsInFlight:
    async def test_the_durable_record_is_paused_and_the_reopen_starts_it_once(self) -> None:
        queued = "exec-trigger-queued"
        gate = AdmissionGate(InMemoryMaintenanceAdapter())
        handler = _LongRunningHandler()
        dispatcher = BackgroundWorkflowDispatcher(
            handler,  # type: ignore[arg-type]
            maintenance=gate,
            budget=ExecutionBudget(1),
        )
        store = _SlowDispatchedSave(queued)
        projection = WorkflowDispatchProjection(
            execution_service=dispatcher,  # type: ignore[arg-type]
            store=store,
        )
        name = projection.PROJECTION_NAME

        await dispatcher.run_workflow("wf", {}, "exec-busy")
        await _let_the_loop_run()
        assert handler.started == ["exec-busy"]

        await store.save(
            name,
            queued,
            {
                "execution_id": queued,
                "workflow_id": "wf",
                "trigger_id": "trigger-1",
                "workflow_inputs": {},
                "status": "pending",
            },
        )
        dispatching = asyncio.create_task(projection.process_pending())
        async with asyncio.timeout(_PATIENCE):
            await store.suspended.wait()
        assert dispatcher.budget.waiting == 1, "the trigger should be queued for a slot"

        async with asyncio.timeout(_PATIENCE):
            await gate.set_mode(active=True, reason="pit stop", actor="deploy")

        # The slot frees while the `dispatched` write is still in flight: the
        # queued trigger reaches it, is refused, and is handed back held.
        handler.may_finish.set()
        await _let_the_loop_run()
        store.release.set()
        async with asyncio.timeout(_PATIENCE):
            await dispatching
            await _drain(dispatcher)

        assert handler.started == ["exec-busy"], "a queued trigger ran behind the pause"
        row = await store.get(name, queued)
        assert row is not None
        assert row["status"] == "paused", (
            "the in-flight `dispatched` write landed over the hand-back: the "
            "trigger never ran and nothing will offer it again"
        )

        await gate.set_mode(active=False, reason="", actor="deploy")
        assert await projection.process_pending() == 1
        async with asyncio.timeout(_PATIENCE):
            await _drain(dispatcher)
        assert await projection.process_pending() == 0
        await _drain(dispatcher)
        assert handler.started == ["exec-busy", queued]


# -- Resumes (#1677): the ResumeStartProcessManager path ----------------------

PARENT = "exec-parent-1617"
_PROJECTION = ResumeStartProcessManager.PROJECTION_NAME


class _ResumeHandler:
    def __init__(self) -> None:
        self.started: list[str] = []

    async def validate(self, parent_execution_id: str) -> ResumeChild:
        return ResumeChild(execution_id=f"{parent_execution_id}-child", workflow_id="wf-1")

    async def handle(
        self, parent_execution_id: str, *, admitted: AdmissionTicket | None = None
    ) -> None:
        if parent_execution_id in self.started:
            return
        self.started.append(parent_execution_id)
        if admitted is not None:
            admitted.mark_visible()


class _ResumeProcess:
    """One API process: its gate, budget, dispatcher and process manager. The
    flag and the to-do store are durable, so a restart is a new instance over
    the same two."""

    def __init__(self, *, port: InMemoryMaintenanceAdapter, store: InMemoryProjectionStore) -> None:
        self.gate = AdmissionGate(port)
        self.store = store
        self.runner = _LongRunningHandler()
        self.resumes = _ResumeHandler()
        self.dispatcher = BackgroundWorkflowDispatcher(
            self.runner,  # type: ignore[arg-type]
            maintenance=self.gate,
            budget=ExecutionBudget(1),
            resume_handler=self.resumes,  # type: ignore[arg-type]
        )
        self.manager = ResumeStartProcessManager(resume_starter=self.dispatcher, store=store)
        self._checkpoints = MemoryCheckpointStore()
        self._nonce = 0

    async def _deliver(self, event: object, event_type: str, aggregate_id: str) -> None:
        self._nonce += 1
        envelope = EventEnvelope(
            event=event,  # type: ignore[arg-type]
            metadata=EventMetadata(
                event_type=event_type,
                aggregate_id=aggregate_id,
                aggregate_type="WorkflowExecution",
                aggregate_nonce=self._nonce,
                global_nonce=self._nonce,
            ),
        )
        await self.manager.handle_event(envelope, self._checkpoints)

    async def the_parent_resumes(self) -> None:
        await self._deliver(
            ExecutionResumedEvent(
                workflow_id="wf-1",
                execution_id=PARENT,
                resume_execution_id=f"{PARENT}-child",
                inherited_phases=[InheritedPhase(phase_id="research", artifact_ids=["a"])],
                resume_phase_id="plan",
                resumed_at=datetime.now(UTC),
            ),
            "ExecutionResumed",
            PARENT,
        )

    async def admission_reopens(self) -> None:
        await self.gate.set_mode(active=False, reason="", actor="deploy")
        await self._deliver(
            AdmissionOpenEvent(announced_at=datetime.now(UTC), actor="deploy"),
            AdmissionOpenEvent.event_type,
            "maintenance",
        )

    async def record(self) -> ResumeStartRecord:
        row = await self.store.get(_PROJECTION, PARENT)
        assert row is not None
        return ResumeStartRecord.model_validate(row)


class TestAResumeQueuedBehindABusySlot:
    async def _queued(self) -> _ResumeProcess:
        process = _ResumeProcess(port=InMemoryMaintenanceAdapter(), store=InMemoryProjectionStore())
        await process.dispatcher.run_workflow("wf", {}, "exec-busy")
        await _let_the_loop_run()
        assert process.runner.started == ["exec-busy"]

        await process.the_parent_resumes()
        assert await process.manager.process_pending() == 1
        assert process.dispatcher.budget.waiting == 1, "the resume should be queued"
        assert (await process.record()).status == "dispatched"
        return process

    async def test_does_not_hold_the_pause_and_is_held_then_started(self) -> None:
        process = await self._queued()

        async with asyncio.timeout(_PATIENCE):
            await process.gate.set_mode(active=True, reason="pit stop", actor="deploy")

        process.runner.may_finish.set()
        async with asyncio.timeout(_PATIENCE):
            await _drain(process.dispatcher)
        assert process.resumes.started == []
        assert (await process.record()).status == "paused", (
            "the resume refused at its slot was not recorded held; nothing would offer it again"
        )

        await process.admission_reopens()
        await process.manager.process_pending()
        async with asyncio.timeout(_PATIENCE):
            await _drain(process.dispatcher)
        assert process.resumes.started == [PARENT]

    async def test_survives_a_restart_while_paused_and_starts_after_the_reopen(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        process = await self._queued()
        async with asyncio.timeout(_PATIENCE):
            await process.gate.set_mode(active=True, reason="pit stop", actor="deploy")

        # The swap: the process dies with the resume still queued.
        await process.dispatcher.shutdown()
        port = process.gate._port  # pyright: ignore[reportPrivateUsage]
        assert isinstance(port, InMemoryMaintenanceAdapter)
        restarted = _ResumeProcess(port=port, store=process.store)
        # The new process re-offers a `dispatched` record once its grace has
        # passed; that is the clock moving, not the behaviour under test.
        monkeypatch.setattr(_start_todo, "DISPATCH_GRACE", timedelta(0))

        await restarted.manager.process_pending()
        await _drain(restarted.dispatcher)
        assert restarted.resumes.started == []
        assert (await restarted.record()).status == "paused"

        await restarted.admission_reopens()
        await restarted.manager.process_pending()
        async with asyncio.timeout(_PATIENCE):
            await _drain(restarted.dispatcher)
        assert restarted.resumes.started == [PARENT]
