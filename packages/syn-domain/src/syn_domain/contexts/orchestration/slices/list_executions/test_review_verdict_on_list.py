"""The review verdict on the execution list, and the filter on it (#1630).

The detail has carried `review_verdict` since PC-63; the list did not, so at
twenty runs nobody could tell certified from blocked without opening each one.
These drive the projection with a real `WorkflowCompleted` payload and read the
rows back through `page()`, the read the API route makes, so a verdict dropped
at the projection, the store or `from_dict` fails here.
"""

from __future__ import annotations

import os

os.environ.setdefault("APP_ENVIRONMENT", "test")

from datetime import UTC, datetime

import pytest

from syn_adapters.projection_stores.memory_store import InMemoryProjectionStore
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    ReviewVerdict,
)
from syn_domain.contexts.orchestration.domain.events.WorkflowCompletedEvent import (
    WorkflowCompletedEvent,
)
from syn_domain.contexts.orchestration.slices.list_executions.projection import (
    WorkflowExecutionListProjection,
)


async def _run(
    projection: WorkflowExecutionListProjection,
    execution_id: str,
    verdict: ReviewVerdict | None,
    *,
    completes: bool = True,
) -> None:
    await projection.on_workflow_execution_started(
        {
            "execution_id": execution_id,
            "workflow_id": "wf-1",
            "workflow_name": "Reviewed",
            "started_at": "2026-11-08T10:00:00Z",
            "total_phases": 3,
        }
    )
    if not completes:
        return
    event = WorkflowCompletedEvent(
        workflow_id="wf-1",
        execution_id=execution_id,
        completed_at=datetime(2026, 11, 8, 11, tzinfo=UTC),
        total_phases=3,
        completed_phases=3,
        total_input_tokens=0,
        total_output_tokens=0,
        total_tokens=0,
        total_duration_seconds=1.0,
        artifact_ids=[],
        review_verdict=verdict,
    )
    await projection.on_workflow_completed(event.model_dump(mode="json"))


@pytest.fixture
async def projection() -> WorkflowExecutionListProjection:
    projection = WorkflowExecutionListProjection(InMemoryProjectionStore())
    await _run(projection, "exec-certified", ReviewVerdict.CERTIFIED)
    await _run(projection, "exec-blocked", ReviewVerdict.BLOCKED)
    await _run(projection, "exec-unreviewed", None)
    await _run(projection, "exec-running", None, completes=False)
    return projection


@pytest.mark.unit
@pytest.mark.asyncio
async def test_the_list_returns_each_runs_verdict(
    projection: WorkflowExecutionListProjection,
) -> None:
    page = await projection.page()

    verdicts = {row.workflow_execution_id: row.review_verdict for row in page.rows}
    assert verdicts == {
        "exec-certified": ReviewVerdict.CERTIFIED,
        "exec-blocked": ReviewVerdict.BLOCKED,
        "exec-unreviewed": None,
        "exec-running": None,
    }


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("verdict", "expected"),
    [(ReviewVerdict.CERTIFIED, "exec-certified"), (ReviewVerdict.BLOCKED, "exec-blocked")],
)
async def test_the_filter_returns_only_runs_on_that_verdict(
    projection: WorkflowExecutionListProjection, verdict: ReviewVerdict, expected: str
) -> None:
    page = await projection.page(review_verdict=verdict)

    assert [row.workflow_execution_id for row in page.rows] == [expected]
    # Counted over the same filtered rows, never the whole list (#1119).
    assert page.total == 1
