"""A resume start that fails inside its task settles, and says so on the parent (#1480).

The operator's view of the failure: `syn execution resume` returns 200, no child
appears, and nothing said why. Two things had to be true to fix it, and this
drives both through the pieces that really run: the REAL process manager over
the REAL dispatcher, whose spawned task raises AFTER `start_resume` returned,
and the record that leaves read back out of `GET /executions/{id}` for the
parent. Only `StartResumeHandler` is a double.
"""

from __future__ import annotations

import asyncio
import importlib
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
from event_sourcing.core.event import EventEnvelope, EventMetadata
from event_sourcing.stores.memory_checkpoint import MemoryCheckpointStore

from syn_adapters.projection_stores import InMemoryProjectionStore

os.environ.setdefault("APP_ENVIRONMENT", "test")

from syn_adapters.maintenance import InMemoryMaintenanceAdapter
from syn_api._wiring_admission import BackgroundWorkflowDispatcher
from syn_domain.contexts.orchestration.slices.start_resume import ResumeChild
from syn_domain.contexts._shared import AdmissionGate
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    InheritedPhase,
)
from syn_domain.contexts.orchestration.domain.events.ExecutionResumedEvent import (
    ExecutionResumedEvent,
)
from syn_domain.contexts.orchestration.domain.events.WorkflowExecutionStartedEvent import (
    WorkflowExecutionStartedEvent,
)
from syn_domain.contexts.orchestration.slices.get_execution_detail.projection import (
    WorkflowExecutionDetailProjection,
)
from syn_domain.contexts.orchestration.slices.start_resume import ResumeStartProcessManager
from syn_domain.contexts.orchestration.slices.start_resume.value_objects import MAX_START_ATTEMPTS

if TYPE_CHECKING:
    from syn_api.routes.executions.models import ExecutionDetailResponse
    from syn_domain.contexts._shared import AdmissionTicket

pytestmark = pytest.mark.unit

PARENT = "exec-parent-1480"
WORKFLOW_ID = "wf-1480"
_AT = datetime(2026, 10, 2, 9, 0, tzinfo=UTC)

#: The process manager's MODULE; the package re-exports the class under its name.
_pm_module = importlib.import_module(
    "syn_domain.contexts.orchestration.slices.start_resume.ResumeStartProcessManager"
)


class _VanishedArtifact(RuntimeError):
    """What the issue names as the realistic case: an inherited artifact is gone."""


class _ResumeHandler:
    """Stands in for StartResumeHandler: admits, then fails inside the task."""

    def __init__(self) -> None:
        self.attempted = 0

    async def validate(self, parent_execution_id: str) -> ResumeChild:
        return ResumeChild(execution_id=f"{parent_execution_id}-child", workflow_id="wf")

    async def handle(
        self, parent_execution_id: str, *, admitted: AdmissionTicket | None = None
    ) -> None:
        del parent_execution_id, admitted
        self.attempted += 1
        raise _VanishedArtifact("artifact art-1 not found")


@dataclass
class _StubProjectionManager:
    store: InMemoryProjectionStore
    workflow_execution_detail: WorkflowExecutionDetailProjection


class _Fixture:
    def __init__(self) -> None:
        self.store = InMemoryProjectionStore()
        self.resumes = _ResumeHandler()
        self.dispatcher = BackgroundWorkflowDispatcher(
            handler=None,  # type: ignore[arg-type]  # the resume path never reaches it
            maintenance=AdmissionGate(InMemoryMaintenanceAdapter()),
            resume_handler=self.resumes,  # type: ignore[arg-type]
        )
        self.manager = ResumeStartProcessManager(resume_starter=self.dispatcher, store=self.store)
        self.detail = WorkflowExecutionDetailProjection(self.store)

    async def the_parent_ran(self) -> None:
        await self.detail.on_workflow_execution_started(
            WorkflowExecutionStartedEvent(
                workflow_id=WORKFLOW_ID,
                execution_id=PARENT,
                workflow_name="review",
                started_at=_AT,
                total_phases=2,
                inputs={},
            ).model_dump()
        )

    async def the_parent_resumes(self) -> None:
        event = ExecutionResumedEvent(
            workflow_id=WORKFLOW_ID,
            execution_id=PARENT,
            resume_execution_id="exec-child-1480",
            inherited_phases=[InheritedPhase(phase_id="research", artifact_ids=["art-1"])],
            resume_phase_id="plan",
            resumed_at=_AT,
        )
        envelope = EventEnvelope(
            event=event,
            metadata=EventMetadata(
                event_type="ExecutionResumed",
                aggregate_id=PARENT,
                aggregate_type="WorkflowExecution",
                aggregate_nonce=1,
                global_nonce=1,
            ),
        )
        await self.manager.handle_event(envelope, MemoryCheckpointStore())

    async def cycle(self, times: int) -> None:
        """Processor passes, each waiting out the task it spawned."""
        for _ in range(times):
            await self.manager.process_pending()
            while self.dispatcher._tasks:  # pyright: ignore[reportPrivateUsage]
                await asyncio.gather(*self.dispatcher._tasks)  # pyright: ignore[reportPrivateUsage]

    async def get(self, monkeypatch: pytest.MonkeyPatch) -> ExecutionDetailResponse:
        from syn_api import _wiring
        from syn_api.routes.executions import queries

        manager = _StubProjectionManager(store=self.store, workflow_execution_detail=self.detail)

        async def _noop_connect() -> None:
            return None

        monkeypatch.setattr(queries, "ensure_connected", _noop_connect)
        monkeypatch.setattr(queries, "get_projection_mgr", lambda: manager)
        monkeypatch.setattr(_wiring, "get_projection_mgr", lambda: manager)
        return await queries.get_execution_endpoint(PARENT)


@pytest.fixture
async def fixture() -> _Fixture:
    built = _Fixture()
    await built.the_parent_ran()
    return built


@pytest.fixture(autouse=True)
def _no_grace(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every pass is as if the grace period had passed, so a record left
    `dispatched` IS re-offered, and what is asserted is whether it settled."""
    monkeypatch.setattr(_pm_module, "DISPATCH_GRACE", timedelta(0))


class TestAResumeStartThatFailsInsideItsTask:
    async def test_the_parent_shows_it_retryable_with_the_cause(
        self, fixture: _Fixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        await fixture.the_parent_resumes()

        await fixture.cycle(1)

        shown = (await fixture.get(monkeypatch)).resume_start
        assert shown is not None, "the parent's detail does not carry its resume start"
        assert (shown.status, shown.attempts, shown.status_reason) == (
            "retryable",
            1,
            "artifact art-1 not found",
        )
        assert shown.max_attempts == MAX_START_ATTEMPTS

    async def test_settles_failed_at_the_ceiling_instead_of_looping(
        self, fixture: _Fixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        await fixture.the_parent_resumes()

        # More passes than the ceiling: a start that loops would keep being
        # attempted, and would never stop reading `dispatched`.
        await fixture.cycle(MAX_START_ATTEMPTS + 3)

        assert fixture.resumes.attempted == MAX_START_ATTEMPTS, "the ceiling did not apply"
        shown = (await fixture.get(monkeypatch)).resume_start
        assert shown is not None
        assert (shown.status, shown.attempts, shown.status_reason) == (
            "failed",
            MAX_START_ATTEMPTS,
            "artifact art-1 not found",
        )

    async def test_it_reaches_the_wire_under_the_field_the_cli_reads(
        self, fixture: _Fixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The CLI reads the serialized JSON, not the model, so check that."""
        await fixture.the_parent_resumes()
        await fixture.cycle(MAX_START_ATTEMPTS)

        wire = (await fixture.get(monkeypatch)).model_dump(mode="json")["resume_start"]

        assert wire["status"] == "failed"
        assert wire["status_reason"] == "artifact art-1 not found"
        assert wire["attempts"] == wire["max_attempts"] == MAX_START_ATTEMPTS


class TestAnExecutionThatWasNeverResumed:
    async def test_carries_no_resume_start(
        self, fixture: _Fixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        assert (await fixture.get(monkeypatch)).resume_start is None
