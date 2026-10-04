"""#1545: an execution whose start the read models never applied must be visible.

exec-db527ea0d361's WorkflowExecutionStarted was in the store at global nonce
39502, every projection checkpoint was at the head, and nothing was logged -
yet both execution read models lacked it. The phase events no-oped against the
missing row and WorkflowFailed later upserted a row with no start, no name and
no phases (#598's fallback). The cause was in the event store (a live
subscriber could skip a nonce whose append committed after a higher one); this
pins the detector that makes the NEXT such drop visible whatever its cause.

The fixture is the incident's own shape, driven through the REAL projections:
two executions of the same workflow, one projected normally and one whose start
event the projections never saw, followed by its phase and terminal events. The
dropped one still has a row by the end - which is why "row exists" is not the
check, and why these tests would pass against a detector that only looked for
absent rows if they did not assert on the degraded row too.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from event_sourcing import EventEnvelope, EventMetadata

from syn_adapters.projection_stores import InMemoryProjectionStore
from syn_api.services.unprojected_executions import (
    UnprojectedExecutionDetector,
    UnprojectedExecutions,
)
from syn_domain.contexts.orchestration.domain.events.PhaseStartedEvent import PhaseStartedEvent
from syn_domain.contexts.orchestration.domain.events.WorkflowExecutionStartedEvent import (
    WorkflowExecutionStartedEvent,
)
from syn_domain.contexts.orchestration.domain.events.WorkflowFailedEvent import WorkflowFailedEvent
from syn_domain.contexts.orchestration.slices.get_execution_detail.projection import (
    WorkflowExecutionDetailProjection,
)
from syn_domain.contexts.orchestration.slices.list_executions.projection import (
    WorkflowExecutionListProjection,
)

pytestmark = pytest.mark.unit

DROPPED = "exec-db527ea0d361"
HEALTHY = "exec-62d51fee08b1"
WORKFLOW_ID = "dreamship-implement-v5"
_AT = datetime(2026, 10, 3, 22, 17, 24, tzinfo=UTC)


def _started(execution_id: str) -> WorkflowExecutionStartedEvent:
    return WorkflowExecutionStartedEvent(
        workflow_id=WORKFLOW_ID,
        execution_id=execution_id,
        workflow_name="dreamship-implement",
        started_at=_AT,
        total_phases=3,
        inputs={},
    )


def _phase_started(execution_id: str) -> PhaseStartedEvent:
    return PhaseStartedEvent(
        workflow_id=WORKFLOW_ID,
        execution_id=execution_id,
        phase_id="implement",
        phase_name="implement",
        phase_order=0,
        started_at=_AT,
    )


def _failed(execution_id: str) -> WorkflowFailedEvent:
    return WorkflowFailedEvent(
        workflow_id=WORKFLOW_ID,
        execution_id=execution_id,
        failed_at=_AT,
        failed_phase_id="implement",
        error_message="agent failed",
        completed_phases=0,
        total_phases=3,
    )


#: (global nonce, handler, event) - the incident's positions where it gave them.
_STREAM = (
    (39490, "on_workflow_execution_started", _started(HEALTHY)),
    (39502, "on_workflow_execution_started", _started(DROPPED)),
    (39519, "on_phase_started", _phase_started(DROPPED)),
    (40800, "on_workflow_failed", _failed(DROPPED)),
)
_HEAD = 40800
_DROPPED_NONCE = 39502


class _Store:
    """The store as the detector sees it: a paged forward read of everything."""

    def __init__(self) -> None:
        self._envelopes = [
            EventEnvelope(
                event=event,
                metadata=EventMetadata(
                    aggregate_id=event.execution_id,
                    aggregate_type="WorkflowExecution",
                    aggregate_nonce=1,
                    global_nonce=nonce,
                    event_type=event.event_type,
                ),
            )
            for nonce, _handler, event in _STREAM
        ]

    async def read_all(
        self, from_global_nonce: int = 0, max_count: int = 100, forward: bool = True
    ) -> tuple[list[EventEnvelope], bool, int]:
        assert forward
        page = [e for e in self._envelopes if (e.metadata.global_nonce or 0) >= from_global_nonce]
        page = page[:max_count]
        nxt = (page[-1].metadata.global_nonce or 0) + 1 if page else from_global_nonce
        is_end = nxt > _HEAD
        return page, is_end, nxt


async def _project(
    *, drop_nonce: int | None
) -> tuple[WorkflowExecutionListProjection, WorkflowExecutionDetailProjection]:
    store = InMemoryProjectionStore()
    listing = WorkflowExecutionListProjection(store)
    detail = WorkflowExecutionDetailProjection(store)
    for nonce, handler_name, event in _STREAM:
        if nonce == drop_nonce:
            continue
        for projection in (listing, detail):
            handler = getattr(projection, handler_name, None)
            if handler is not None:
                await handler(event.model_dump())
    return listing, detail


def _detector(
    listing: WorkflowExecutionListProjection, detail: WorkflowExecutionDetailProjection
) -> UnprojectedExecutionDetector:
    return UnprojectedExecutionDetector(_Store(), lookups=(listing.get_by_id, detail.get_by_id))


class TestADroppedStartIsReported:
    @pytest.mark.asyncio
    async def test_the_incident_row_is_reported_although_it_exists(self) -> None:
        """The terminal handler upserted a row; it still has no start."""
        listing, detail = await _project(drop_nonce=_DROPPED_NONCE)
        row = await detail.get_by_id(DROPPED)
        assert row is not None and row.started_at is None, "fixture must reproduce #1545's row"

        result = await _detector(listing, detail).check(settled_through=_HEAD)

        assert result.execution_ids == (DROPPED,), (
            f"{DROPPED}'s start is in the store at {_DROPPED_NONCE} and neither read model "
            f"applied it; the detector reported {result.execution_ids}"
        )
        warning = result.describe()
        assert warning is not None and DROPPED in warning

    @pytest.mark.asyncio
    async def test_a_fully_projected_store_reports_nothing(self) -> None:
        listing, detail = await _project(drop_nonce=None)

        result = await _detector(listing, detail).check(settled_through=_HEAD)

        assert result == UnprojectedExecutions(execution_ids=(), checked_through=_HEAD)
        assert result.describe() is None

    @pytest.mark.asyncio
    async def test_a_start_the_projections_have_not_reached_is_lag_not_a_drop(self) -> None:
        listing, detail = await _project(drop_nonce=_DROPPED_NONCE)

        result = await _detector(listing, detail).check(settled_through=_DROPPED_NONCE - 1)

        assert result.execution_ids == ()

    @pytest.mark.asyncio
    async def test_a_repaired_row_stops_being_reported(self) -> None:
        """Rebuild replays the start; the next check must clear, not stay stuck."""
        listing, detail = await _project(drop_nonce=_DROPPED_NONCE)
        detector = _detector(listing, detail)
        assert (await detector.check(settled_through=_HEAD)).execution_ids == (DROPPED,)

        for projection in (listing, detail):
            await projection.on_workflow_execution_started(_started(DROPPED).model_dump())

        assert (await detector.check(settled_through=_HEAD)).execution_ids == ()
