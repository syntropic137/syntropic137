"""How a run ended its review reaches the read model the API serves (PC-63).

Fed the payload `WorkflowCompletedEvent` actually serialises to, and read back
through the projection's own query, so a field dropped at either hop - the
handler or the row's `from_dict` - fails here rather than in the API.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from syn_adapters.projection_stores import InMemoryProjectionStore
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    ReviewVerdict,
)
from syn_domain.contexts.orchestration.domain.events.WorkflowCompletedEvent import (
    WorkflowCompletedEvent,
)
from syn_domain.contexts.orchestration.slices.get_execution_detail.projection import (
    WorkflowExecutionDetailProjection,
)

pytestmark = pytest.mark.unit


def _completed(verdict: ReviewVerdict | None) -> dict[str, object]:
    return WorkflowCompletedEvent(
        workflow_id="wf",
        execution_id="exec-1",
        completed_at=datetime(2026, 10, 5, tzinfo=UTC),
        total_phases=10,
        completed_phases=10,
        total_input_tokens=0,
        total_output_tokens=0,
        total_tokens=0,
        total_duration_seconds=1.0,
        artifact_ids=[],
        review_verdict=verdict,
    ).model_dump(mode="json")


async def _ended_on(verdict: ReviewVerdict | None) -> ReviewVerdict | None:
    projection = WorkflowExecutionDetailProjection(InMemoryProjectionStore())
    await projection.on_workflow_execution_started(
        {"execution_id": "exec-1", "workflow_id": "wf", "workflow_name": "wf", "phases": []}
    )
    await projection.on_workflow_completed(_completed(verdict))
    detail = await projection.get_by_id("exec-1")
    assert detail is not None
    assert detail.status == "completed"
    return detail.review_verdict


class TestTheReadModelSaysHowTheReviewEnded:
    async def test_a_run_blocked_at_the_bound_reads_as_unresolved(self) -> None:
        assert await _ended_on(ReviewVerdict.BLOCKED) is ReviewVerdict.BLOCKED

    async def test_a_certified_run_reads_as_certified(self) -> None:
        assert await _ended_on(ReviewVerdict.CERTIFIED) is ReviewVerdict.CERTIFIED

    async def test_a_run_that_reviewed_nothing_reads_as_no_verdict(self) -> None:
        assert await _ended_on(None) is None
