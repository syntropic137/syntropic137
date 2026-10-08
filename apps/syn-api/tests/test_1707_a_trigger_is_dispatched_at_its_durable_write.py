"""#1707: a trigger is `dispatched` at its execution's durable write, not at the end of its run.

The dispatcher used to confirm a start when `handle` returned, which is the end
of the whole run, and to report every exception from it as a start that never
happened. So a running execution's trigger stayed `queued`, and one whose run
failed after the write - its local projection, say - was recorded `failed`
although its execution exists.

The confirmation now rides the admission ticket to the write itself. These run
the REAL dispatcher, projection and :class:`WorkflowExecutionProcessor`; only
the execution repository and the to-do list are doubles, so the write can be
seen and the run suspended just past it. The handler hands the command
straight to the processor, the way `ExecuteWorkflowHandler` does once the
workflow is loaded.
"""

from __future__ import annotations

import asyncio
import os
from typing import TYPE_CHECKING

import pytest
from event_sourcing.core.event import EventEnvelope, EventMetadata
from event_sourcing.stores.memory_checkpoint import MemoryCheckpointStore

from syn_adapters.projection_stores.memory_store import InMemoryProjectionStore

os.environ.setdefault("APP_ENVIRONMENT", "test")

from syn_adapters.maintenance import InMemoryMaintenanceAdapter
from syn_api._wiring_admission import BackgroundWorkflowDispatcher
from syn_api.execution_budget import ExecutionBudget
from syn_domain.contexts._shared import AdmissionGate
from syn_domain.contexts.github.domain.events.TriggerFiredEvent import TriggerFiredEvent
from syn_domain.contexts.github.slices.dispatch_triggered_workflow.projection import (
    WorkflowDispatchProjection,
)
from syn_domain.contexts.orchestration.slices.execute_workflow import (
    test_1387_the_lease_ends_at_the_durable_write as durable,
)

if TYPE_CHECKING:
    from syn_domain.contexts._shared import AdmissionTicket
    from syn_domain.contexts.orchestration import ExecuteWorkflowCommand
    from syn_domain.contexts.orchestration.slices.execute_workflow.processor_types import (
        WorkflowExecutionResult,
    )

pytestmark = pytest.mark.unit

_PATIENCE = 5.0
_TRIGGERED = "exec-trigger-1707-write"


class _ProjectionThatFails(durable._SuspendedTodoList):  # pyright: ignore[reportPrivateUsage]
    """The local to-do projection, failing on the start event the store already holds."""

    async def on_workflow_execution_started(self, event: object) -> None:
        del event
        msg = "local projection failed after save_new"
        raise OSError(msg)


class _Handler:
    def __init__(
        self,
        repository: durable._Recorded,  # pyright: ignore[reportPrivateUsage]
        todos: durable._SuspendedTodoList,  # pyright: ignore[reportPrivateUsage]
    ) -> None:
        self._processor = durable._processor(repository, todos)  # pyright: ignore[reportPrivateUsage]

    async def validate_stored_declarations(self, _workflow_id: str) -> None:
        return None

    async def handle(
        self, command: ExecuteWorkflowCommand, *, admitted: AdmissionTicket | None = None
    ) -> WorkflowExecutionResult:
        return await self._processor.run(
            workflow_id=command.aggregate_id,
            workflow_name="A triggered workflow",
            phases=durable._one_phase(),  # pyright: ignore[reportPrivateUsage]
            inputs=dict(command.inputs),
            execution_id=command.execution_id or "",
            admitted=admitted,
        )


class _Process:
    def __init__(self, todos: durable._SuspendedTodoList) -> None:  # pyright: ignore[reportPrivateUsage]
        self.repository = durable._Recorded()  # pyright: ignore[reportPrivateUsage]
        self.todos = todos
        self.store = InMemoryProjectionStore()
        self.dispatcher = BackgroundWorkflowDispatcher(
            _Handler(self.repository, todos),  # type: ignore[arg-type]
            maintenance=AdmissionGate(InMemoryMaintenanceAdapter()),
            budget=ExecutionBudget(1),
        )
        self.projection = WorkflowDispatchProjection(
            execution_service=self.dispatcher,  # type: ignore[arg-type]
            store=self.store,
        )

    async def a_trigger_fires_and_is_offered(self) -> None:
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
        assert await self.projection.process_pending() == 1

    async def status(self) -> tuple[str, str | None]:
        found = await self.store.get(WorkflowDispatchProjection.PROJECTION_NAME, _TRIGGERED)
        assert found is not None, "the trigger produced no dispatch record at all"
        reason = found.get("status_reason")
        return str(found.get("status")), None if reason is None else str(reason)

    async def finish(self) -> None:
        self.todos.may_continue.set()
        async with asyncio.timeout(_PATIENCE):
            while self.dispatcher._tasks:  # pyright: ignore[reportPrivateUsage]
                await asyncio.gather(*self.dispatcher._tasks)  # pyright: ignore[reportPrivateUsage]
                await asyncio.sleep(0)


class TestAStartWhoseWriteSucceeded:
    async def test_is_dispatched_before_its_run_continues(self) -> None:
        process = _Process(durable._SuspendedTodoList())  # pyright: ignore[reportPrivateUsage]
        try:
            await process.a_trigger_fires_and_is_offered()
            async with asyncio.timeout(_PATIENCE):
                await process.todos.reached.wait()

            assert process.repository.opened == [_TRIGGERED], (
                "the run had not reached the durable write, so this proves nothing"
            )
            assert await process.status() == ("dispatched", None), (
                "the execution is durable and running, and its trigger still says it may "
                "not exist - a restart now would offer it again"
            )
            await process.finish()
        finally:
            await process.dispatcher.shutdown()

    async def test_is_still_dispatched_when_its_run_fails_after_the_write(self) -> None:
        todos = _ProjectionThatFails()
        todos.may_continue.set()
        process = _Process(todos)
        try:
            await process.a_trigger_fires_and_is_offered()
            await process.finish()

            assert process.repository.opened == [_TRIGGERED], (
                "the write never happened, so this is a pre-start failure and proves nothing"
            )
            assert await process.status() == ("dispatched", None), (
                "an execution that exists was recorded as a start that could not happen"
            )
            assert await process.projection.process_pending() == 0
        finally:
            await process.dispatcher.shutdown()


class TestAStartWhoseWriteFailed:
    async def test_is_failed_and_not_offered_again(self) -> None:
        process = _Process(durable._SuspendedTodoList())  # pyright: ignore[reportPrivateUsage]
        process.repository.fail_with = OSError("event store unavailable")
        try:
            await process.a_trigger_fires_and_is_offered()
            await process.finish()

            assert process.repository.opened == []
            assert await process.status() == ("failed", "start_exception")
            assert await process.projection.process_pending() == 0
        finally:
            await process.dispatcher.shutdown()
