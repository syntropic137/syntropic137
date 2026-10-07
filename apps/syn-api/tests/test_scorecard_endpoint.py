"""GET /insights/scorecard renders what the projection recorded, cost and all."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from event_sourcing import DomainEvent, EventEnvelope, EventMetadata, ProjectionResult
from event_sourcing.stores.memory_checkpoint import MemoryCheckpointStore

from syn_adapters.projection_stores import InMemoryProjectionStore
from syn_api.services.scorecard import WindowError, build_scorecard, parse_window
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    FailureClassification,
    ResumeOrigin,
)
from syn_domain.contexts.orchestration.domain.events.PhaseCompletedEvent import (
    PhaseCompletedEvent,
)
from syn_domain.contexts.orchestration.domain.events.WorkflowCompletedEvent import (
    WorkflowCompletedEvent,
)
from syn_domain.contexts.orchestration.domain.events.WorkflowExecutionStartedEvent import (
    WorkflowExecutionStartedEvent,
)
from syn_domain.contexts.orchestration.domain.events.WorkflowFailedEvent import (
    WorkflowFailedEvent,
)
from syn_domain.contexts.orchestration.slices.scorecard import ScorecardProjection

if TYPE_CHECKING:
    from collections.abc import Iterable

pytestmark = pytest.mark.unit

NOW = datetime(2026, 10, 7, 18, 0, tzinfo=UTC)


async def _costs(ids: Iterable[str]) -> dict[str, Decimal]:
    known = {"parent": Decimal("4.25"), "child": Decimal("1.50")}
    return {i: known[i] for i in ids if i in known}


async def _tool_calls(session_ids: Iterable[str]) -> dict[str, int]:
    return dict.fromkeys(session_ids, 12)


async def _deliver(projection: ScorecardProjection, event: DomainEvent) -> None:
    """Through ``handle_event``: the payload the handler gets is the real ``model_dump()``."""
    envelope = EventEnvelope(
        event=event,
        metadata=EventMetadata(
            aggregate_id="execution",
            aggregate_type="WorkflowExecution",
            aggregate_nonce=1,
            event_type=event.event_type,
            global_nonce=1,
        ),
    )
    result = await projection.handle_event(envelope, MemoryCheckpointStore())
    assert result is ProjectionResult.SUCCESS


@pytest.mark.asyncio
async def test_the_response_carries_a_resumed_chains_full_cost_and_one_outcome() -> None:
    store = InMemoryProjectionStore()
    projection = ScorecardProjection(store)
    # The parent ended two days ago: outside a 1d window, inside its chain.
    await _deliver(
        projection,
        WorkflowExecutionStartedEvent(
            workflow_id="wf",
            execution_id="parent",
            workflow_name="implement",
            started_at=datetime(2026, 10, 5, 10, 0, tzinfo=UTC),
            total_phases=2,
            inputs={},
        ),
    )
    await _deliver(
        projection,
        WorkflowFailedEvent(
            workflow_id="wf",
            execution_id="parent",
            failed_at=datetime(2026, 10, 5, 11, 0, tzinfo=UTC),
            error_message="workspace died",
            failure_classification=FailureClassification.PLATFORM,
            completed_phases=0,
            total_phases=2,
        ),
    )
    await _deliver(
        projection,
        WorkflowExecutionStartedEvent(
            workflow_id="wf",
            execution_id="child",
            workflow_name="implement",
            started_at=datetime(2026, 10, 7, 10, 0, tzinfo=UTC),
            total_phases=2,
            inputs={},
            resumed_from=ResumeOrigin(
                parent_execution_id="parent", inherited_phases=[], resume_phase_id="verify_2"
            ),
        ),
    )
    await _deliver(
        projection,
        PhaseCompletedEvent(
            workflow_id="wf",
            execution_id="child",
            phase_id="verify_2",
            completed_at=datetime(2026, 10, 7, 11, 0, tzinfo=UTC),
            success=True,
            session_id="s1",
            total_tokens=2_500_000,
        ),
    )
    await _deliver(
        projection,
        WorkflowCompletedEvent(
            workflow_id="wf",
            execution_id="child",
            completed_at=datetime(2026, 10, 7, 12, 0, tzinfo=UTC),
            total_phases=2,
            completed_phases=2,
            total_input_tokens=0,
            total_output_tokens=0,
            total_tokens=2_500_000,
            total_duration_seconds=7200.0,
            artifact_ids=[],
        ),
    )

    response = await build_scorecard(
        store=store, read_costs=_costs, read_tool_calls=_tool_calls, window="1d", now=NOW
    )

    assert response.counts.total == 1
    assert response.counts.completed == 1
    assert response.counts.completed_platform_failure_free == 0
    assert response.total_cost_usd == "5.75"
    assert response.total_cost_display == "$5.75"
    assert response.phases[0].phase_type == "verify"
    assert response.phases[0].median_tokens_display == "2.5M"
    assert response.phases[0].median_tool_calls == 12.0
    verify_target = next(t for t in response.targets if t.name == "Median verify tokens")
    assert verify_target.status == "on_track"
    assert response.delivery.merged_prs is None
    assert response.daily[-1].day == "2026-10-07"


def test_window_must_be_a_day_count() -> None:
    assert parse_window("7d") == 7
    for bad in ("0d", "31d", "7", "week"):
        with pytest.raises(WindowError):
            parse_window(bad)
