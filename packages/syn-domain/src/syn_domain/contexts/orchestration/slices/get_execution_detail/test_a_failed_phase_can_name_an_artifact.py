"""#1321: the read model an operator opens has to show what a failure kept.

The processor now takes a failing phase's deliverable out of the workspace
before that workspace is abandoned, and ``WorkflowFailed`` carries the ids.
This is the other end of that: until this handler reads them, the artifact is
stored and nothing in the execution detail points at it - which is the same
"delivered nothing" the issue reports, one layer further out.

``artifact_id`` on a failed phase was unconditionally ``None`` before, because
the only handler that ever set it was ``on_phase_completed``. So the one field
an operator looks at to find a refused phase's work was the one field
guaranteed to be empty for a refused phase.

THE PAYLOAD IS THE REAL EVENT'S. ``AutoDispatchProjection.handle_event`` calls
the handler with ``envelope.event.model_dump()``, so these tests dump a real
``WorkflowFailedEvent`` rather than hand-writing the dict it produces. That is
deliberate: the ids are carried across three hops with the key spelled by hand
at each one, and a test holding its own copy of the spelling passes at both
ends of a hop that drops them. The one payload written by hand below is the
one no current event can produce - a failure recorded before the field existed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import pytest

from syn_adapters.projection_stores import InMemoryProjectionStore
from syn_domain.contexts.orchestration.domain.events.WorkflowFailedEvent import (
    WorkflowFailedEvent,
)
from syn_domain.contexts.orchestration.slices.get_execution_detail.projection import (
    WorkflowExecutionDetailProjection,
)

pytestmark = pytest.mark.unit

EXECUTION_ID = "exec-1321"


@pytest.fixture
def projection() -> WorkflowExecutionDetailProjection:
    return WorkflowExecutionDetailProjection(InMemoryProjectionStore())


async def _phase_in_flight(proj: WorkflowExecutionDetailProjection) -> None:
    """A started execution with one running phase, built by the handlers.

    Driving the real handlers rather than seeding a hand-shaped record keeps
    the phase's fields whatever ``PhaseDetail.running`` actually writes -
    including the ``artifact_id: None`` this change is about, which a hand-copy
    would keep asserting long after the shape moved.
    """
    await proj.on_workflow_execution_started(
        {
            "execution_id": EXECUTION_ID,
            "workflow_id": "wf-1321",
            "workflow_name": "1321",
            "total_phases": 1,
        }
    )
    await proj.on_phase_started(
        {
            "execution_id": EXECUTION_ID,
            "phase_id": "research",
            "phase_name": "Research",
            "started_at": "2026-09-17T09:00:00Z",
        }
    )


async def _fail(proj: WorkflowExecutionDetailProjection, kept: list[str]) -> None:
    """Fail the run the way the stream does: a real event, dumped."""
    event = WorkflowFailedEvent(
        workflow_id="wf-1321",
        execution_id=EXECUTION_ID,
        failed_at=datetime(2026, 9, 17, 10, 0, tzinfo=UTC),
        failed_phase_id="research",
        error_message="Phase research reported an unreadable TASK_RESULT",
        failed_phase_artifact_ids=kept,
        completed_phases=0,
        total_phases=1,
    )
    await proj.on_workflow_failed(event.model_dump())


@dataclass(frozen=True)
class _AsStored:
    """What an operator opening the execution detail would see of #1321."""

    phase_status: str | None
    artifact_id: str | None
    execution_artifact_ids: list[str]


async def _read_back(proj: WorkflowExecutionDetailProjection) -> _AsStored:
    record = await proj._store.get(proj.PROJECTION_NAME, EXECUTION_ID)
    assert record is not None, "the failure handler must leave a record to read"
    phases = record.get("phases") or [{}]
    return _AsStored(
        phase_status=phases[0].get("status"),
        artifact_id=phases[0].get("artifact_id"),
        execution_artifact_ids=record.get("artifact_ids") or [],
    )


class TestAFailedPhaseNamesWhatWasKept:
    async def test_the_failed_phase_carries_the_artifact_id(
        self, projection: WorkflowExecutionDetailProjection
    ) -> None:
        await _phase_in_flight(projection)
        await _fail(projection, ["art-1"])

        stored = await _read_back(projection)
        assert stored.artifact_id == "art-1", (
            "The failed phase's record must name what was kept from it; None "
            "here is an artifact nothing links to."
        )
        assert stored.phase_status == "failed", "The phase still failed."

    async def test_the_execution_lists_the_artifacts(
        self, projection: WorkflowExecutionDetailProjection
    ) -> None:
        """``artifact_ids: []`` on a failed execution is the line in the issue."""
        await _phase_in_flight(projection)
        await _fail(projection, ["art-1", "art-2"])

        assert (await _read_back(projection)).execution_artifact_ids == ["art-1", "art-2"]

    async def test_an_orphaned_failure_still_lists_them(
        self, projection: WorkflowExecutionDetailProjection
    ) -> None:
        """No stored execution to attach a phase to (#598) - the ids are still
        real, and dropping them here would lose exactly the artifacts nothing
        else records."""
        await _fail(projection, ["art-1"])

        assert (await _read_back(projection)).execution_artifact_ids == ["art-1"]

    async def test_an_event_that_kept_nothing_changes_neither(
        self, projection: WorkflowExecutionDetailProjection
    ) -> None:
        """A failure recorded before the field existed. Written out rather than
        dumped because the current event cannot produce it: the field defaults
        to ``[]`` and ``model_dump`` always writes it, so only a stored payload
        from before #1321 has the key missing altogether."""
        await _phase_in_flight(projection)
        await projection.on_workflow_failed(
            {
                "execution_id": EXECUTION_ID,
                "workflow_id": "wf-1321",
                "failed_phase_id": "research",
                "error_message": "Phase research reported an unreadable TASK_RESULT",
                "failed_at": "2026-09-17T10:00:00Z",
            }
        )

        stored = await _read_back(projection)
        assert stored.artifact_id is None
        assert stored.execution_artifact_ids == []
