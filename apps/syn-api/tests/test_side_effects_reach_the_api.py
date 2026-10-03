"""A completed run whose PR comment was refused says so in `GET /executions/{id}`.

The field crosses six hand-listed hops - projection dict, `PhaseDetail`,
`PhaseExecutionDetail`, `PhaseExecution`, `PhaseExecutionInfo`, and the
execution-level `ExecutionDetailFull` -> `ExecutionDetailResponse` - and this
repository has dropped a field at such a hop before (#891, #1176, #1319). So
the value goes in as real events and is read out of the HTTP response model.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from syn_adapters.projection_stores import InMemoryProjectionStore
from syn_domain.contexts.orchestration import SideEffectStatus
from syn_domain.contexts.orchestration.domain.events.PhaseCompletedEvent import (
    PhaseCompletedEvent,
)
from syn_domain.contexts.orchestration.domain.events.PhaseStartedEvent import PhaseStartedEvent
from syn_domain.contexts.orchestration.domain.events.WorkflowCompletedEvent import (
    WorkflowCompletedEvent,
)
from syn_domain.contexts.orchestration.domain.events.WorkflowExecutionStartedEvent import (
    WorkflowExecutionStartedEvent,
)
from syn_domain.contexts.orchestration.slices.get_execution_detail.projection import (
    WorkflowExecutionDetailProjection,
)

if TYPE_CHECKING:
    from event_sourcing import DomainEvent

    from syn_api.routes.executions.models import ExecutionDetailResponse

pytestmark = pytest.mark.unit

EXECUTION_ID = "exec-side-effects"
WORKFLOW_ID = "wf-review"
_AT = datetime(2026, 10, 1, 18, 0, tzinfo=UTC)


def _phase_started(phase_id: str, order: int) -> PhaseStartedEvent:
    return PhaseStartedEvent(
        workflow_id=WORKFLOW_ID,
        execution_id=EXECUTION_ID,
        phase_id=phase_id,
        phase_name=phase_id,
        phase_order=order,
        started_at=_AT,
    )


def _phase_completed(
    phase_id: str, reported: SideEffectStatus | None, artifact_id: str | None
) -> PhaseCompletedEvent:
    return PhaseCompletedEvent(
        workflow_id=WORKFLOW_ID,
        execution_id=EXECUTION_ID,
        phase_id=phase_id,
        completed_at=_AT,
        success=True,
        artifact_id=artifact_id,
        reported_side_effects=reported,
        input_tokens=10,
        output_tokens=5,
        duration_seconds=3.0,
    )


def _stream(
    phases: list[tuple[str, SideEffectStatus | None, str | None]], *, started: bool = True
) -> list[tuple[str, DomainEvent]]:
    events: list[tuple[str, DomainEvent]] = [
        (
            "on_workflow_execution_started",
            WorkflowExecutionStartedEvent(
                workflow_id=WORKFLOW_ID,
                execution_id=EXECUTION_ID,
                workflow_name="review",
                started_at=_AT,
                total_phases=len(phases),
                inputs={},
            ),
        )
    ]
    for order, (phase_id, reported, artifact_id) in enumerate(phases):
        if started:
            events.append(("on_phase_started", _phase_started(phase_id, order)))
        events.append(("on_phase_completed", _phase_completed(phase_id, reported, artifact_id)))
    artifact_ids = [a for _, _, a in phases if a]
    events.append(
        (
            "on_workflow_completed",
            WorkflowCompletedEvent(
                workflow_id=WORKFLOW_ID,
                execution_id=EXECUTION_ID,
                completed_at=_AT,
                total_phases=len(phases),
                completed_phases=len(phases),
                total_input_tokens=10,
                total_output_tokens=5,
                total_tokens=15,
                total_duration_seconds=3.0,
                artifact_ids=artifact_ids,
            ),
        )
    )
    return events


@dataclass
class _StubProjectionManager:
    store: InMemoryProjectionStore
    workflow_execution_detail: WorkflowExecutionDetailProjection


async def _get(
    monkeypatch: pytest.MonkeyPatch,
    phases: list[tuple[str, SideEffectStatus | None, str | None]],
    *,
    started: bool = True,
) -> ExecutionDetailResponse:
    from syn_api import _wiring
    from syn_api.routes.executions import queries

    store = InMemoryProjectionStore()
    projection = WorkflowExecutionDetailProjection(store)
    for handler, event in _stream(phases, started=started):
        await getattr(projection, handler)(event.model_dump())
    manager = _StubProjectionManager(store=store, workflow_execution_detail=projection)

    async def _noop_connect() -> None:
        return None

    monkeypatch.setattr(queries, "ensure_connected", _noop_connect)
    monkeypatch.setattr(queries, "get_projection_mgr", lambda: manager)
    monkeypatch.setattr(_wiring, "get_projection_mgr", lambda: manager)
    return await queries.get_execution_endpoint(EXECUTION_ID)


class TestARefusedWriteBackOnACompletedRun:
    @pytest.mark.asyncio
    async def test_the_run_is_completed_with_its_deliverable_and_says_denied(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        detail = await _get(monkeypatch, [("review", SideEffectStatus.DENIED, "art-1")])

        assert detail.status == "completed"
        assert detail.deliverable_produced is True
        assert detail.reported_side_effects is SideEffectStatus.DENIED
        assert [p.reported_side_effects for p in detail.phases] == [SideEffectStatus.DENIED]

    @pytest.mark.asyncio
    async def test_a_completion_with_no_start_event_carries_it_too(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The projection's other branch builds the phase record from scratch."""
        detail = await _get(
            monkeypatch, [("review", SideEffectStatus.DENIED, "art-1")], started=False
        )

        assert [p.reported_side_effects for p in detail.phases] == [SideEffectStatus.DENIED]
        assert detail.reported_side_effects is SideEffectStatus.DENIED

    @pytest.mark.asyncio
    async def test_the_execution_reports_its_worst_phase(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        detail = await _get(
            monkeypatch,
            [
                ("implement", SideEffectStatus.SUCCEEDED, "art-1"),
                ("review", SideEffectStatus.DENIED, "art-2"),
            ],
        )

        assert detail.reported_side_effects is SideEffectStatus.DENIED


class TestNothingIsInventedWhereNothingWasSaid:
    @pytest.mark.asyncio
    async def test_a_phase_that_reported_nothing_reads_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        detail = await _get(monkeypatch, [("review", None, "art-1")])

        assert detail.reported_side_effects is None
        assert [p.reported_side_effects for p in detail.phases] == [None]

    @pytest.mark.asyncio
    async def test_no_artifact_means_no_deliverable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        detail = await _get(monkeypatch, [("review", SideEffectStatus.NONE, None)])

        assert detail.deliverable_produced is False
