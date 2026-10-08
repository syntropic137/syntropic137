"""A trigger refused for a full disk is held, not dropped (#1560).

The admission floor protects Postgres from ENOSPC mid-run, but a refusal is
only honest if the work it refused is still owed. A trigger has no operator
behind it to press retry: if its record says ``failed``, nothing ever offers it
again, so a disk that filled for ten minutes would silently lose every webhook,
poll and check-run that arrived in them.

Driven through the REAL bridge (``BackgroundWorkflowDispatcher``) and the real
``AdmissionGate``, with only the measurement faked, because the defect lived in
the seam: the gate raised a new refusal the dispatcher did not recognise.
"""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

import pytest
from event_sourcing.core.event import EventEnvelope, EventMetadata
from event_sourcing.stores.memory_checkpoint import MemoryCheckpointStore
from event_sourcing.stores.memory_projection import MemoryProjectionStore

os.environ.setdefault("APP_ENVIRONMENT", "test")

from syn_adapters.maintenance import InMemoryMaintenanceAdapter
from syn_api._wiring_admission import BackgroundWorkflowDispatcher
from syn_domain.contexts._shared import (
    AdmissionGate,
    AdmissionRefusedError,
    AdmissionTicket,
    RepositoryRef,
)
from syn_domain.contexts._shared.disk_space import DiskSpaceGuard, DiskUsage
from syn_domain.contexts.github.domain.events.TriggerFiredEvent import TriggerFiredEvent
from syn_domain.contexts.github.slices.dispatch_triggered_workflow.projection import (
    WorkflowDispatchProjection,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.processor_types import (
    WorkflowExecutionResult,
)

pytestmark = pytest.mark.unit

_PROJECTION = WorkflowDispatchProjection.PROJECTION_NAME
_EXECUTION = "exec-disk-1560"
_GIB = 2**30


class _MutableDisk:
    """`DiskSpacePort` double whose free space the test changes between passes."""

    def __init__(self, free_percent: float) -> None:
        self.free_percent = free_percent

    @property
    def path(self) -> str:
        return "/workspaces"

    def usage(self) -> DiskUsage:
        total = 100 * _GIB
        return DiskUsage(free_bytes=int(total * self.free_percent / 100), total_bytes=total)


class _RecordingHandler:
    """Stands in for ExecuteWorkflowHandler. Records what was admitted."""

    def __init__(self) -> None:
        self.admitted: list[object] = []

    async def validate_stored_declarations(self, _workflow_id: str) -> None:
        return None

    async def handle(
        self, command: object, *, admitted: AdmissionTicket | None = None
    ) -> WorkflowExecutionResult:
        self.admitted.append(command)
        if admitted is not None:
            admitted.mark_visible()
        # The dispatcher reads the result it is given (#1547).
        return WorkflowExecutionResult(
            workflow_id="wf",
            execution_id=getattr(command, "execution_id", "") or "",
            status="completed",
            started_at=datetime(2026, 10, 5, tzinfo=UTC),
        )


class _Fixture:
    def __init__(self) -> None:
        self.disk = _MutableDisk(free_percent=3.0)
        self.store = MemoryProjectionStore()
        self.handler = _RecordingHandler()
        gate = AdmissionGate(
            InMemoryMaintenanceAdapter(),
            disk=DiskSpaceGuard(
                self.disk, degraded_below_percent=10.0, refuse_admission_below_percent=5.0
            ),
        )
        self.dispatcher = BackgroundWorkflowDispatcher(
            self.handler,  # type: ignore[arg-type]
            maintenance=gate,
        )
        self.projection = WorkflowDispatchProjection(
            execution_service=self.dispatcher, store=self.store
        )

    async def a_trigger_fires(self) -> None:
        event = TriggerFiredEvent(
            trigger_id="trg-ci-self-healing",
            execution_id=_EXECUTION,
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
        await self.projection.handle_event(envelope, MemoryCheckpointStore())

    async def status(self) -> tuple[str, str | None]:
        found = await self.store.get(_PROJECTION, _EXECUTION)
        assert found is not None, "the trigger produced no dispatch record at all"
        reason = found.get("status_reason")
        return str(found.get("status")), None if reason is None else str(reason)

    async def drain(self) -> None:
        while self.dispatcher._tasks:
            await asyncio.gather(*self.dispatcher._tasks)


class TestATriggerThatFiresBelowTheFreeSpaceFloor:
    async def test_is_held_with_the_disk_named_as_the_reason(self) -> None:
        fixture = _Fixture()
        await fixture.a_trigger_fires()

        await fixture.projection.process_pending()
        await fixture.drain()

        assert await fixture.status() == ("paused", "insufficient_disk_space")
        assert fixture.handler.admitted == []

    async def test_is_dispatched_from_its_saved_record_once_space_is_freed(self) -> None:
        fixture = _Fixture()
        await fixture.a_trigger_fires()
        await fixture.projection.process_pending()

        fixture.disk.free_percent = 40.0
        await fixture.projection.process_pending()
        await fixture.drain()

        assert (await fixture.status())[0] == "dispatched"
        assert len(fixture.handler.admitted) == 1


class _RoadClosedError(AdmissionRefusedError):
    """A refusal reason that does not exist yet. The dispatcher has never heard of it."""

    hold_reason = "road_closed"


class _RefusingService:
    async def run_workflow(
        self,
        workflow_id: str,
        inputs: dict[str, str],
        execution_id: str,
        task: str | None = None,
        repos: list[RepositoryRef] | None = None,
        on_held: Callable[[Exception], Awaitable[None]] | None = None,
        on_started: Callable[[], Awaitable[None]] | None = None,
    ) -> AdmissionTicket | None:
        del workflow_id, inputs, execution_id, task, repos, on_held, on_started
        raise _RoadClosedError("the road is closed")

    def holds_execution(self, execution_id: str) -> bool:
        del execution_id
        return False


class TestTheNextAdmissionRefusalReason:
    async def test_is_held_under_its_own_name_without_the_dispatcher_naming_it(self) -> None:
        # The disk refusal was dropped because the dispatcher caught refusals
        # by name. Holding a reason invented here proves it catches the family.
        fixture = _Fixture()
        fixture.projection = WorkflowDispatchProjection(
            execution_service=_RefusingService(), store=fixture.store
        )
        await fixture.a_trigger_fires()

        await fixture.projection.process_pending()

        assert await fixture.status() == ("paused", "road_closed")
