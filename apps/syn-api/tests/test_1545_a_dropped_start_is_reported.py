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

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from event_sourcing import EventEnvelope, EventMetadata
from httpx import ASGITransport, AsyncClient

from syn_adapters.projection_stores import InMemoryProjectionStore
from syn_adapters.subscriptions.coordinator_service import SubscriptionServiceStatus
from syn_adapters.subscriptions.read_model_lag import (
    CheckpointState,
    ReadModelLag,
    measure_read_model_lag,
)
from syn_api.services import lifecycle, unprojected_executions
from syn_api.services.unprojected_executions import (
    EXECUTION_PROJECTIONS,
    UnprojectedExecutionDetector,
    UnprojectedExecutions,
    check_once,
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

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable

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
    """The store as the detector sees it: a paged forward read of what is committed.

    `uncommitted` holds nonces that were allocated but whose append has not
    committed yet, so a read cannot see them - #1545's late commit.
    """

    def __init__(self, *, uncommitted: frozenset[int] = frozenset()) -> None:
        self.uncommitted = set(uncommitted)
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
        page = [
            e
            for e in self._envelopes
            if (e.metadata.global_nonce or 0) >= from_global_nonce
            and e.metadata.global_nonce not in self.uncommitted
        ]
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
    listing: WorkflowExecutionListProjection,
    detail: WorkflowExecutionDetailProjection,
    store: _Store | None = None,
) -> UnprojectedExecutionDetector:
    return UnprojectedExecutionDetector(
        store or _Store(), lookups=(listing.get_by_id, detail.get_by_id)
    )


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


class TestEveryCheckIsAFullReconciliation:
    """Transitions an incremental scan gets wrong (verification of #1559)."""

    @pytest.mark.asyncio
    async def test_a_start_that_commits_after_a_higher_nonce_is_still_found(self) -> None:
        """#1545's own mechanism: 39502 becomes visible after 40800 was read.

        A cursor that advanced to 40801 on the first check would never read
        39502, so the drop it exists to report would stay invisible for good.
        """
        listing, detail = await _project(drop_nonce=_DROPPED_NONCE)
        store = _Store(uncommitted=frozenset({_DROPPED_NONCE}))
        detector = _detector(listing, detail, store)
        assert (await detector.check(settled_through=_HEAD)).execution_ids == ()

        store.uncommitted.clear()  # the slow append commits

        assert (await detector.check(settled_through=_HEAD)).execution_ids == (DROPPED,)

    @pytest.mark.asyncio
    async def test_a_row_lost_after_a_clean_check_is_reported(self) -> None:
        listing, detail = await _project(drop_nonce=None)
        detector = _detector(listing, detail)
        assert (await detector.check(settled_through=_HEAD)).execution_ids == ()

        await detail.clear_all_data()  # a botched rebuild, a truncation, ...

        assert (await detector.check(settled_through=_HEAD)).execution_ids == (HEALTHY, DROPPED)


class _SubscriptionStub:
    """The two methods /health and the watch call on the coordinator service."""

    def get_status(self) -> SubscriptionServiceStatus:
        return SubscriptionServiceStatus(running=True, projection_count=2, realtime_enabled=True)

    async def describe_read_model_lag(self) -> ReadModelLag:
        return measure_read_model_lag(
            head_position=_HEAD,
            checkpoints={
                name: CheckpointState(position=_HEAD, updated_at=_AT)
                for name in EXECUTION_PROJECTIONS
            },
            projection_names=list(EXECUTION_PROJECTIONS),
            replaying=False,
            now=_AT,
        )


@pytest.fixture
async def health_warnings() -> AsyncIterator[Callable[[], Awaitable[list[str]]]]:
    """Reads `warnings` off the real /health route, with the subscription stubbed."""
    from syn_api.main import create_app

    original_service = lifecycle._state.subscription_service
    original_latest = unprojected_executions._watch.latest
    lifecycle._state.subscription_service = _SubscriptionStub()  # type: ignore[assignment]  # stub
    unprojected_executions._watch.latest = None
    app = create_app()

    async def get() -> list[str]:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/health")
        assert response.status_code == 200
        return json.loads(response.text).get("warnings") or []

    try:
        yield get
    finally:
        lifecycle._state.subscription_service = original_service
        unprojected_executions._watch.latest = original_latest


class TestTheWatchFeedsHealth:
    @pytest.mark.asyncio
    async def test_a_drop_appears_on_health_and_clears_on_repair(
        self, health_warnings: Callable[[], Awaitable[list[str]]]
    ) -> None:
        listing, detail = await _project(drop_nonce=_DROPPED_NONCE)
        detector = _detector(listing, detail)
        publish = unprojected_executions._watch.publish
        assert not any(DROPPED in w for w in await health_warnings())

        await check_once(_SubscriptionStub(), detector, publish)
        assert any(DROPPED in w for w in await health_warnings()), "/health must name the drop"

        for projection in (listing, detail):
            await projection.on_workflow_execution_started(_started(DROPPED).model_dump())
        await check_once(_SubscriptionStub(), detector, publish)
        assert not any(DROPPED in w for w in await health_warnings())
