"""Every declared phase reaches the detail response, with where it stands (cee46909).

The execution detail page drew `phases`, which holds only the phases that
started, so a viewer could not see what was left. `phase_plan` is every phase
the run declared. It has to survive the projection dict, the read model,
`ExecutionDetailFull` and `ExecutionDetailResponse`, so these replay real events
into the REAL projection and read `GET /executions/{id}`.

Each run is also checked against the progress figure beside it, because a list
that counts different phases from `phase_progress` is the "2 of 10" contradiction
feedback 9a95d8f7 was about.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from syn_adapters.projection_stores import InMemoryProjectionStore
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    InheritedPhase,
    PhaseDefinition,
    ResumeOrigin,
)
from syn_domain.contexts.orchestration.domain.events.NextPhaseReadyEvent import (
    NextPhaseReadyEvent,
)
from syn_domain.contexts.orchestration.domain.events.PhaseCompletedEvent import (
    PhaseCompletedEvent,
)
from syn_domain.contexts.orchestration.domain.events.PhaseStartedEvent import PhaseStartedEvent
from syn_domain.contexts.orchestration.domain.events.WorkflowExecutionStartedEvent import (
    WorkflowExecutionStartedEvent,
)
from syn_domain.contexts.orchestration.slices.get_execution_detail.projection import (
    WorkflowExecutionDetailProjection,
)
from syn_domain.contexts.orchestration.slices.list_executions.projection import (
    WorkflowExecutionListProjection,
)

if TYPE_CHECKING:
    from event_sourcing import DomainEvent

    from syn_api.routes.executions.models import ExecutionDetailResponse

pytestmark = pytest.mark.unit

EXECUTION_ID = "exec-cee46909"
WORKFLOW_ID = "wf-cee46909"
_AT = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)


def _started(
    phase_ids: list[str],
    resumed_from: ResumeOrigin | None = None,
) -> WorkflowExecutionStartedEvent:
    # Declared out of order on purpose: the plan follows `order`, not the list.
    definitions = [
        PhaseDefinition(phase_id=p, name=p.title(), order=i) for i, p in enumerate(phase_ids)
    ]
    return WorkflowExecutionStartedEvent(
        workflow_id=WORKFLOW_ID,
        execution_id=EXECUTION_ID,
        workflow_name="cee46909",
        started_at=_AT,
        total_phases=len(phase_ids),
        inputs={},
        phase_definitions=[asdict(d) for d in reversed(definitions)],
        resumed_from=resumed_from,
    )


def _phase_started(phase_id: str, order: int) -> PhaseStartedEvent:
    return PhaseStartedEvent(
        workflow_id=WORKFLOW_ID,
        execution_id=EXECUTION_ID,
        phase_id=phase_id,
        phase_name=phase_id,
        phase_order=order,
        started_at=_AT,
    )


def _phase_completed(phase_id: str) -> PhaseCompletedEvent:
    return PhaseCompletedEvent(
        workflow_id=WORKFLOW_ID,
        execution_id=EXECUTION_ID,
        phase_id=phase_id,
        completed_at=_AT,
        success=True,
        input_tokens=11,
        output_tokens=7,
        duration_seconds=12.5,
    )


def _next_phase_ready(
    completed: str, next_phase: str, order: int, skipped: list[str]
) -> NextPhaseReadyEvent:
    return NextPhaseReadyEvent(
        workflow_id=WORKFLOW_ID,
        execution_id=EXECUTION_ID,
        completed_phase_id=completed,
        next_phase_id=next_phase,
        next_phase_order=order,
        decided_at=_AT,
        skipped_phase_ids=skipped,
    )


#: (handler, event) pairs, as the subscription would dispatch them.
type Stream = list[tuple[str, DomainEvent]]

#: (a) A fresh run mid-way: plan done, implement running, two phases to come.
FRESH_MID_RUN: Stream = [
    ("on_workflow_execution_started", _started(["plan", "implement", "verify", "report"])),
    ("on_phase_started", _phase_started("plan", 0)),
    ("on_phase_completed", _phase_completed("plan")),
    ("on_phase_started", _phase_started("implement", 1)),
]

#: (b) The first review certified, so both repair rounds were skipped (PC-63).
CERTIFIED_EARLY: Stream = [
    (
        "on_workflow_execution_started",
        _started(["implement", "review", "fix_2", "reverify_2", "report"]),
    ),
    ("on_phase_started", _phase_started("implement", 0)),
    ("on_phase_completed", _phase_completed("implement")),
    ("on_phase_started", _phase_started("review", 1)),
    ("on_phase_completed", _phase_completed("review")),
    ("on_next_phase_ready", _next_phase_ready("review", "report", 4, ["fix_2", "reverify_2"])),
    ("on_phase_started", _phase_started("report", 4)),
]

#: (c) A resume that took `implement` over from its parent and is now on `verify`.
RESUMED: Stream = [
    (
        "on_workflow_execution_started",
        _started(
            ["implement", "verify", "report"],
            resumed_from=ResumeOrigin(
                parent_execution_id="exec-parent",
                inherited_phases=[InheritedPhase(phase_id="implement", artifact_ids=["art-1"])],
                resume_phase_id="verify",
            ),
        ),
    ),
    ("on_phase_started", _phase_started("verify", 1)),
]


async def _replay(projection: object, stream: Stream) -> None:
    for handler_name, event in stream:
        handler = getattr(projection, handler_name, None)
        if handler is not None:
            await handler(event.model_dump())


@dataclass
class _StubProjectionManager:
    """Everything the detail route reads hard; cost and sessions fail soft."""

    store: InMemoryProjectionStore
    workflow_execution_detail: WorkflowExecutionDetailProjection


async def _detail_response(
    monkeypatch: pytest.MonkeyPatch, stream: Stream
) -> ExecutionDetailResponse:
    """Serve `GET /executions/{id}` off a projection built from ``stream``."""
    from syn_api import _wiring
    from syn_api.routes.executions import queries

    store = InMemoryProjectionStore()
    projection = WorkflowExecutionDetailProjection(store)
    await _replay(projection, stream)
    manager = _StubProjectionManager(store=store, workflow_execution_detail=projection)

    async def _noop_connect() -> None:
        return None

    monkeypatch.setattr(queries, "ensure_connected", _noop_connect)
    monkeypatch.setattr(queries, "get_projection_mgr", lambda: manager)
    monkeypatch.setattr(_wiring, "get_projection_mgr", lambda: manager)
    return await queries.get_execution_endpoint(EXECUTION_ID)


def _statuses(response: ExecutionDetailResponse) -> list[tuple[str, str]]:
    return [(p.phase_id, p.status) for p in response.phase_plan]


def _assert_plan_agrees_with_progress(response: ExecutionDetailResponse) -> None:
    """The plan counts the phases the progress figure counts (feedback 9a95d8f7)."""
    plan = response.phase_plan
    assert len(plan) == response.total_phases
    not_skipped = [p for p in plan if p.status != "skipped"]
    assert len(not_skipped) == response.phase_progress.possible
    assert sum(p.status == "skipped" for p in plan) == response.phase_progress.skipped


@pytest.mark.asyncio
async def test_a_fresh_run_mid_way_lists_the_phases_still_to_come(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = await _detail_response(monkeypatch, FRESH_MID_RUN)

    assert _statuses(response) == [
        ("plan", "completed"),
        ("implement", "running"),
        ("verify", "pending"),
        ("report", "pending"),
    ]
    assert [p.name for p in response.phase_plan] == ["Plan", "Implement", "Verify", "Report"]
    assert response.phase_plan[2].status_display == "Pending"
    # `phases` keeps its meaning: only what started.
    assert [p.phase_id for p in response.phases] == ["plan", "implement"]
    _assert_plan_agrees_with_progress(response)
    assert response.phase_progress.display == "phase 2 of up to 4"


@pytest.mark.asyncio
async def test_skipped_repair_rounds_read_skipped_not_pending(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = await _detail_response(monkeypatch, CERTIFIED_EARLY)

    assert _statuses(response) == [
        ("implement", "completed"),
        ("review", "completed"),
        ("fix_2", "skipped"),
        ("reverify_2", "skipped"),
        ("report", "running"),
    ]
    assert response.phase_plan[2].status_display == "Skipped (not needed)"
    _assert_plan_agrees_with_progress(response)
    assert response.phase_progress.display == "phase 3 of up to 3 (2 phases not needed)"


@pytest.mark.asyncio
async def test_a_resume_shows_its_inherited_phases_as_inherited(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = await _detail_response(monkeypatch, RESUMED)

    assert _statuses(response) == [
        ("implement", "inherited"),
        ("verify", "running"),
        ("report", "pending"),
    ]
    assert response.phase_plan[0].status_display == "Inherited (completed earlier)"
    # The inherited phase is counted as completed, and only listed, not run here.
    assert response.completed_phases == 1
    assert [p.phase_id for p in response.phases] == ["verify"]
    _assert_plan_agrees_with_progress(response)


@pytest.mark.asyncio
async def test_the_plan_counts_what_the_list_view_counts() -> None:
    """The list's progress denominator and the detail's plan come from one event."""
    detail = WorkflowExecutionDetailProjection(InMemoryProjectionStore())
    listing = WorkflowExecutionListProjection(InMemoryProjectionStore())
    await _replay(detail, CERTIFIED_EARLY)
    await _replay(listing, CERTIFIED_EARLY)

    detail_row = await detail.get_by_id(EXECUTION_ID)
    list_row = await listing.get_by_id(EXECUTION_ID)
    assert detail_row is not None
    assert list_row is not None
    assert len(detail_row.phase_plan) == list_row.total_phases == 5
    assert detail_row.phase_progress == list_row.phase_progress


@pytest.mark.asyncio
async def test_a_run_that_declared_no_phases_still_shows_what_started(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Start events before ISS-196 carry no definitions; nothing more is known."""
    legacy = WorkflowExecutionStartedEvent(
        workflow_id=WORKFLOW_ID,
        execution_id=EXECUTION_ID,
        workflow_name="legacy",
        started_at=_AT,
        total_phases=3,
        inputs={},
    )
    stream: Stream = [
        ("on_workflow_execution_started", legacy),
        ("on_phase_started", _phase_started("implement", 0)),
    ]
    response = await _detail_response(monkeypatch, stream)

    assert _statuses(response) == [("implement", "running")]
