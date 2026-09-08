"""#1147: the detail endpoint must report how many phases a run set out to do.

`GET /executions/{id}` reported no `total_phases` at all while `GET /executions`
reported 3 for the same run, because the detail projection read nine fields off
`WorkflowExecutionStarted` where the list projection read ten. On the execution
detail page a three-phase run that died in phase one rendered as a one-phase
execution: the two phases that never started were indistinguishable from phases
that do not exist.

These drive the REAL projection with a real event stream and then read the
answer out of the HTTP response model, because the defect lives in the hops
between - the projection dict, the read model, `ExecutionDetailFull` and
`ExecutionDetailResponse` each have to carry the field, and any one of them
dropping it puts the page back to counting `phases`, which is a different
number by construction.

The fixture is a run that COMPLETED ONE PHASE OF THREE AND THEN FAILED, so
every number here is distinguishable from every default and from
`len(phases)`: 3 total, 1 completed, 2 phases in the list.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from syn_adapters.projection_stores import InMemoryProjectionStore
from syn_domain.contexts.orchestration.domain.events.PhaseCompletedEvent import (
    PhaseCompletedEvent,
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
    from event_sourcing import AutoDispatchProjection, DomainEvent

    from syn_api.routes.executions.models import ExecutionDetailResponse

pytestmark = pytest.mark.unit

#: The execution from the issue's own reproduction.
EXECUTION_ID = "exec-0cd860b80128"
WORKFLOW_ID = "wf-1147"
TOTAL_PHASES = 3
COMPLETED_PHASES = 1
#: What the detail view counted instead: the phases that had reached it.
PHASES_SEEN = 2

_STARTED_AT = datetime(2026, 9, 7, 18, 0, tzinfo=UTC)
_FAILED_AT = datetime(2026, 9, 7, 18, 30, tzinfo=UTC)


def _started() -> WorkflowExecutionStartedEvent:
    return WorkflowExecutionStartedEvent(
        workflow_id=WORKFLOW_ID,
        execution_id=EXECUTION_ID,
        workflow_name="implement-verify-report",
        started_at=_STARTED_AT,
        total_phases=TOTAL_PHASES,
        inputs={},
    )


def _phase_started(phase_id: str, order: int) -> PhaseStartedEvent:
    return PhaseStartedEvent(
        workflow_id=WORKFLOW_ID,
        execution_id=EXECUTION_ID,
        phase_id=phase_id,
        phase_name=phase_id,
        phase_order=order,
        started_at=_STARTED_AT,
    )


def _phase_completed(phase_id: str) -> PhaseCompletedEvent:
    return PhaseCompletedEvent(
        workflow_id=WORKFLOW_ID,
        execution_id=EXECUTION_ID,
        phase_id=phase_id,
        completed_at=_STARTED_AT,
        success=True,
        input_tokens=11,
        output_tokens=7,
        duration_seconds=12.5,
    )


def _failed() -> WorkflowFailedEvent:
    return WorkflowFailedEvent(
        workflow_id=WORKFLOW_ID,
        execution_id=EXECUTION_ID,
        failed_at=_FAILED_AT,
        failed_phase_id="verify",
        error_message="phase timed out",
        completed_phases=COMPLETED_PHASES,
        total_phases=TOTAL_PHASES,
    )


#: One run, as it happened: implement finished, verify started, the run died.
#: Built from the event classes themselves, so a field renamed on an event
#: fails here rather than leaving a hand-written fixture agreeing with nothing.
def _stream() -> tuple[tuple[str, DomainEvent], ...]:
    return (
        ("on_workflow_execution_started", _started()),
        ("on_phase_started", _phase_started("implement", 0)),
        ("on_phase_completed", _phase_completed("implement")),
        ("on_phase_started", _phase_started("verify", 1)),
        ("on_workflow_failed", _failed()),
    )


async def _replay(projection: AutoDispatchProjection) -> None:
    """Feed the stream to whichever handlers a projection declares.

    Skipping the rest is what AutoDispatchProjection does with an event nobody
    subscribed to, and it is why the same stream can drive both views: the list
    projection has no ``on_phase_started``, which is a legitimate difference in
    what it needs to know, unlike the field it and the detail view derive from
    the SAME event and used to disagree about.
    """
    for handler_name, event in _stream():
        handler = getattr(projection, handler_name, None)
        if handler is not None:
            await handler(event.model_dump())


@dataclass
class _StubProjectionManager:
    """Everything the detail route reads, and nothing it only reads soft.

    Cost, tool operations and agent session ids all fail soft in the route, so
    their absence here exercises the same path a Lane 2 outage does.
    """

    store: InMemoryProjectionStore
    workflow_execution_detail: WorkflowExecutionDetailProjection


async def _detail_response(monkeypatch: pytest.MonkeyPatch) -> ExecutionDetailResponse:
    """Serve `GET /executions/{id}` off a projection built from real events."""
    from syn_api import _wiring
    from syn_api.routes.executions import queries

    store = InMemoryProjectionStore()
    projection = WorkflowExecutionDetailProjection(store)
    await _replay(projection)

    manager = _StubProjectionManager(store=store, workflow_execution_detail=projection)

    async def _noop_connect() -> None:
        return None

    monkeypatch.setattr(queries, "ensure_connected", _noop_connect)
    monkeypatch.setattr(queries, "get_projection_mgr", lambda: manager)
    monkeypatch.setattr(_wiring, "get_projection_mgr", lambda: manager)

    return await queries.get_execution_endpoint(EXECUTION_ID)


class TestTheDetailEndpointReportsTheRealPhaseCount:
    @pytest.mark.asyncio
    async def test_total_phases_is_what_the_workflow_set_out_to_do(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The reported null, and the 1 the page derived from `phases`."""
        response = await _detail_response(monkeypatch)

        assert response.total_phases == TOTAL_PHASES, (
            f"detail reports total_phases={response.total_phases} for a run whose "
            f"WorkflowExecutionStarted event stated {TOTAL_PHASES}; the list view "
            "reads the same field off the same event (#1147)"
        )

    @pytest.mark.asyncio
    async def test_total_phases_is_not_the_length_of_the_phase_list(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The two numbers are different, and the gap is the point.

        `len(phases)` counts what started. A client with only that number
        cannot tell a run that had three phases and reached two from a run that
        only ever had two.
        """
        response = await _detail_response(monkeypatch)

        assert len(response.phases) == PHASES_SEEN
        assert response.total_phases - len(response.phases) == 1, (
            "the phases that never started are only visible as this gap"
        )

    @pytest.mark.asyncio
    async def test_completed_phases_survives_to_the_response(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The sibling field, omitted by the same handler for the same reason."""
        response = await _detail_response(monkeypatch)

        assert response.completed_phases == COMPLETED_PHASES


class TestTheTwoViewsAgree:
    """The defect was divergence, so the test is on the divergence itself."""

    @pytest.mark.asyncio
    async def test_list_and_detail_report_the_same_counts_for_one_event_stream(
        self,
    ) -> None:
        detail = WorkflowExecutionDetailProjection(InMemoryProjectionStore())
        listing = WorkflowExecutionListProjection(InMemoryProjectionStore())
        await _replay(detail)
        await _replay(listing)

        detail_row = await detail.get_by_id(EXECUTION_ID)
        list_row = await listing.get_by_id(EXECUTION_ID)
        assert detail_row is not None
        assert list_row is not None

        assert (detail_row.total_phases, detail_row.completed_phases) == (
            list_row.total_phases,
            list_row.completed_phases,
        ), (
            f"one event stream, two answers: detail says "
            f"{detail_row.total_phases}/{detail_row.completed_phases} and list says "
            f"{list_row.total_phases}/{list_row.completed_phases} (#1147)"
        )
        assert detail_row.total_phases == TOTAL_PHASES


class TestPhaseCountsWithoutATerminalEvent:
    """A run still in flight has no completion event to restate its counts."""

    @pytest.mark.asyncio
    async def test_a_running_execution_accumulates_completed_phases(self) -> None:
        projection = WorkflowExecutionDetailProjection(InMemoryProjectionStore())
        await projection.on_workflow_execution_started(_started().model_dump())
        await projection.on_phase_started(_phase_started("implement", 0).model_dump())
        await projection.on_phase_completed(_phase_completed("implement").model_dump())
        await projection.on_phase_started(_phase_started("verify", 1).model_dump())
        await projection.on_phase_completed(_phase_completed("verify").model_dump())

        row = await projection.get_by_id(EXECUTION_ID)
        assert row is not None
        assert (row.completed_phases, row.total_phases) == (2, TOTAL_PHASES), (
            "a run mid-flight must report 2 of 3, not 2 of 2 (#1147)"
        )
