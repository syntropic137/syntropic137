"""An admitted resume's child is started through the gate, and says how it went.

The same seam as #1387's trigger path, and the same hazard (#1039): the
process manager awaits `start_resume()` and then writes a status, so a refusal
raised inside the fire-and-forget task would leave a record claiming a child
that never started. So these run the REAL process manager over the REAL
dispatcher and gate; only `StartResumeHandler` is a double, because what it does
once admitted is proven in the domain against the real processor.
"""

from __future__ import annotations

import asyncio
import importlib
import os
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
from event_sourcing.core.event import EventEnvelope, EventMetadata
from event_sourcing.stores.memory_checkpoint import MemoryCheckpointStore

from syn_adapters.projection_stores.memory_store import InMemoryProjectionStore

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
from syn_domain.contexts.orchestration.domain.events.ExecutionResumedEvent import (
    ExecutionResumedEvent,
)
from syn_domain.contexts.orchestration.slices.start_resume import (
    ResumeChild,
    ResumeStartProcessManager,
    ResumeStartRecord,
)
from syn_domain.contexts.orchestration.slices.start_resume.value_objects import MAX_START_ATTEMPTS

pytestmark = pytest.mark.unit

PARENT = "exec-parent-1454"

#: The start to-do list module, where DISPATCH_GRACE is read (#1557).
#: Imported by path so the module, not a re-exported name, is patched.
_pm_module = importlib.import_module("syn_domain.contexts.orchestration._shared.start_todo")
_PROJECTION = ResumeStartProcessManager.PROJECTION_NAME


class _ResumeHandler:
    """Stands in for StartResumeHandler: refuses on request, records what it started."""

    def __init__(self) -> None:
        self.refusal: str | None = None
        #: Raised from INSIDE the spawned task - after `validate` passed and
        #: `start_resume` returned - which is where a real start fails when a
        #: store, a repository or a workspace gives out mid-start (#1463).
        self.fails_in_task: Exception | None = None
        self.attempted = 0
        self.started: list[str] = []

    async def validate(self, parent_execution_id: str) -> ResumeChild:
        if self.refusal is not None:
            raise ValueError(self.refusal)
        return ResumeChild(execution_id=f"{parent_execution_id}-child", workflow_id="wf-1")

    async def handle(
        self, parent_execution_id: str, *, admitted: AdmissionTicket | None = None
    ) -> None:
        # Idempotent per parent, because the real `StartResumeHandler.handle` is:
        # it returns early when the child already exists, and the child's id is
        # fixed by the parent's `ExecutionResumed` rather than minted per attempt.
        # That matters now that a `dispatched` record stays OWED and is therefore
        # re-offered on later processor passes - a fake that appended every time
        # would report a double start the real one cannot perform.
        if parent_execution_id in self.started:
            return
        self.attempted += 1
        if self.fails_in_task is not None:
            raise self.fails_in_task
        self.started.append(parent_execution_id)
        if admitted is not None:
            admitted.mark_visible()


class _Fixture:
    def __init__(self) -> None:
        self.store = InMemoryProjectionStore()
        self.checkpoints = MemoryCheckpointStore()
        self.resumes = _ResumeHandler()
        self.maintenance = AdmissionGate(InMemoryMaintenanceAdapter())
        self.dispatcher = BackgroundWorkflowDispatcher(
            handler=None,  # type: ignore[arg-type]  # the resume path never reaches it
            maintenance=self.maintenance,
            resume_handler=self.resumes,  # type: ignore[arg-type]
        )
        self.manager = ResumeStartProcessManager(resume_starter=self.dispatcher, store=self.store)
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

    async def the_parent_resumes(self) -> None:
        event = ExecutionResumedEvent(
            workflow_id="wf-1",
            execution_id=PARENT,
            resume_execution_id="exec-child-1454",
            inherited_phases=[InheritedPhase(phase_id="research", artifact_ids=["art-1"])],
            resume_phase_id="plan",
            resumed_at=datetime.now(UTC),
        )
        await self._deliver(event, "ExecutionResumed", PARENT)

    async def admission_reopens(self) -> None:
        await self._deliver(
            AdmissionOpenEvent(announced_at=datetime.now(UTC), actor="deploy"),
            AdmissionOpenEvent.event_type,
            "maintenance",
        )

    async def record(self) -> ResumeStartRecord:
        row = await self.store.get(_PROJECTION, PARENT)
        assert row is not None, "the resume produced no start record at all"
        return ResumeStartRecord.model_validate(row)

    async def drain(self) -> None:
        while self.dispatcher._tasks:  # pyright: ignore[reportPrivateUsage]
            await asyncio.gather(*self.dispatcher._tasks)  # pyright: ignore[reportPrivateUsage]


@pytest.fixture
async def fixture() -> _Fixture:
    return _Fixture()


class TestAnAdmittedResume:
    async def test_is_owed_a_start_before_anything_runs(self, fixture: _Fixture) -> None:
        await fixture.the_parent_resumes()

        assert (await fixture.record()).status == "pending"
        assert fixture.resumes.started == []

    async def test_is_started_once_processed(self, fixture: _Fixture) -> None:
        await fixture.the_parent_resumes()

        assert await fixture.manager.process_pending() == 1
        await fixture.drain()

        # `dispatched`, not `started`: the starter has been called, and nothing
        # yet proves a child stream exists. Only the child's own
        # `WorkflowExecutionStarted` settles that (#1459 review).
        assert (await fixture.record()).status == "dispatched"
        assert fixture.resumes.started == [PARENT]

    async def test_a_replayed_resume_does_not_reopen_a_started_record(
        self, fixture: _Fixture
    ) -> None:
        await fixture.the_parent_resumes()
        await fixture.manager.process_pending()
        await fixture.drain()

        await fixture.the_parent_resumes()
        await fixture.manager.process_pending()
        await fixture.drain()

        assert (await fixture.record()).status == "dispatched"
        assert fixture.resumes.started == [PARENT], "the resume was started twice"


class TestAResumeStartedWhileAdmissionIsPaused:
    async def test_starts_nothing_and_is_recorded_paused(self, fixture: _Fixture) -> None:
        await fixture.the_parent_resumes()
        await fixture.maintenance.set_mode(active=True, reason="pit stop", actor="deploy")

        assert await fixture.manager.process_pending() == 0
        await fixture.drain()

        assert (await fixture.record()).status == "paused"
        assert fixture.resumes.started == []

    async def test_is_started_once_admission_reopens(self, fixture: _Fixture) -> None:
        await fixture.the_parent_resumes()
        await fixture.maintenance.set_mode(active=True, reason="pit stop", actor="deploy")
        await fixture.manager.process_pending()

        await fixture.maintenance.set_mode(active=False, reason="", actor="deploy")
        await fixture.admission_reopens()
        await fixture.manager.process_pending()
        await fixture.drain()

        assert (await fixture.record()).status == "dispatched"
        assert fixture.resumes.started == [PARENT]


class TestAResumeTheChildRefuses:
    async def test_is_recorded_failed_with_the_reason_not_started(self, fixture: _Fixture) -> None:
        """#1039: the refusal must reach the record, not die in a background task."""
        fixture.resumes.refusal = "Cannot start resume exec-child-1454: no pinned phase config"
        await fixture.the_parent_resumes()

        await fixture.manager.process_pending()
        await fixture.drain()

        record = await fixture.record()
        assert record.status == "failed"
        assert record.status_reason == fixture.resumes.refusal
        assert fixture.resumes.started == []

    async def test_is_not_retried(self, fixture: _Fixture) -> None:
        fixture.resumes.refusal = "refused"
        await fixture.the_parent_resumes()
        await fixture.manager.process_pending()

        fixture.resumes.refusal = None
        assert await fixture.manager.process_pending() == 0
        assert fixture.resumes.started == []


class TestAResumeStartThatFailsInsideItsTask:
    """#1463. `validate` passed, `start_resume` returned, then the task raised.

    That failure used to reach only a log line: the record stayed `dispatched`,
    `attempts` never moved, `status_reason` stayed None, and the start was
    re-offered after every grace period for ever - each time taking an
    admission ticket. The synchronous path already settled after
    `MAX_START_ATTEMPTS`; this is the same bound, applied to the path that ran.
    """

    @pytest.fixture(autouse=True)
    def _no_grace(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Every cycle below is as if the grace period had passed.

        So a record left `dispatched` IS re-offered each cycle, and what the
        assertions see is whether an attempt was counted - not whether the
        clock moved.
        """
        monkeypatch.setattr(_pm_module, "DISPATCH_GRACE", timedelta(0))

    async def _cycle(self, fixture: _Fixture, times: int) -> None:
        for _ in range(times):
            await fixture.manager.process_pending()
            await fixture.drain()

    async def test_is_retryable_with_the_reason_after_one_attempt(self, fixture: _Fixture) -> None:
        fixture.resumes.fails_in_task = RuntimeError("workspace provider unreachable")
        await fixture.the_parent_resumes()

        await self._cycle(fixture, 1)

        record = await fixture.record()
        assert (record.status, record.attempts) == ("retryable", 1)
        assert record.status_reason == "workspace provider unreachable"

    async def test_settles_failed_once_the_attempts_are_spent(self, fixture: _Fixture) -> None:
        fixture.resumes.fails_in_task = RuntimeError("workspace provider unreachable")
        await fixture.the_parent_resumes()

        await self._cycle(fixture, MAX_START_ATTEMPTS + 3)

        record = await fixture.record()
        assert record.status == "failed"
        assert record.attempts == MAX_START_ATTEMPTS
        assert record.status_reason == "workspace provider unreachable"
        assert fixture.resumes.attempted == MAX_START_ATTEMPTS, "the bound did not apply"

    async def test_a_refusal_inside_the_task_is_terminal_at_once(self, fixture: _Fixture) -> None:
        """Classified as the synchronous path classifies it: a `ValueError` is
        the domain's refusal, and asking again gets the same answer."""
        fixture.resumes.fails_in_task = ValueError("Cannot start resume: refused")
        await fixture.the_parent_resumes()

        await self._cycle(fixture, 3)

        record = await fixture.record()
        assert (record.status, record.status_reason) == ("failed", "Cannot start resume: refused")
        assert fixture.resumes.attempted == 1
