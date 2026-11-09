"""#1630: an execution's review verdict reaches the list, and `?review_verdict=` filters by it.

The detail has served `review_verdict` since PC-63; the list did not, so
telling certified runs from blocked ones meant opening each. These replay real
`WorkflowCompleted` events into the real projections and call the real route
functions, so a response model that does not declare the field, a constructor
that does not pass it, or a route that accepts the filter and never hands it
to the read model, all fail here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import pytest

from syn_adapters.projection_stores import InMemoryProjectionStore
from syn_domain.contexts.orchestration import ReviewVerdict
from syn_domain.contexts.orchestration.domain.events.WorkflowCompletedEvent import (
    WorkflowCompletedEvent,
)
from syn_domain.contexts.orchestration.domain.events.WorkflowExecutionStartedEvent import (
    WorkflowExecutionStartedEvent,
)
from syn_domain.contexts.orchestration.slices.get_execution_detail.projection import (
    WorkflowExecutionDetailProjection,
)
from syn_domain.contexts.orchestration.slices.list_executions.projection import (
    WorkflowExecutionListProjection,
)

pytestmark = pytest.mark.unit

WORKFLOW_ID = "wf-1630"
VERDICTS: dict[str, ReviewVerdict | None] = {
    "exec-certified-1630": ReviewVerdict.CERTIFIED,
    "exec-blocked-1630": ReviewVerdict.BLOCKED,
    "exec-unreviewed-1630": None,
}


@dataclass
class _StubProjectionManager:
    store: InMemoryProjectionStore
    workflow_execution_detail: WorkflowExecutionDetailProjection
    workflow_execution_list: WorkflowExecutionListProjection


async def _serve(monkeypatch: pytest.MonkeyPatch) -> None:
    from syn_api import _wiring
    from syn_api.routes.executions import queries

    store = InMemoryProjectionStore()
    detail = WorkflowExecutionDetailProjection(store)
    listing = WorkflowExecutionListProjection(store)
    for execution_id, verdict in VERDICTS.items():
        started = WorkflowExecutionStartedEvent(
            workflow_id=WORKFLOW_ID,
            execution_id=execution_id,
            workflow_name="reviewed",
            started_at=datetime(2026, 11, 8, 9, 0, tzinfo=UTC),
            total_phases=3,
            inputs={},
        ).model_dump()
        completed = WorkflowCompletedEvent(
            workflow_id=WORKFLOW_ID,
            execution_id=execution_id,
            completed_at=datetime(2026, 11, 8, 10, 0, tzinfo=UTC),
            total_phases=3,
            completed_phases=3,
            total_input_tokens=0,
            total_output_tokens=0,
            total_tokens=0,
            total_duration_seconds=1.0,
            artifact_ids=[],
            review_verdict=verdict,
        ).model_dump()
        for projection in (detail, listing):
            await projection.on_workflow_execution_started(started)
            await projection.on_workflow_completed(completed)
    manager = _StubProjectionManager(
        store=store, workflow_execution_detail=detail, workflow_execution_list=listing
    )

    async def _noop_connect() -> None:
        return None

    monkeypatch.setattr(queries, "ensure_connected", _noop_connect)
    monkeypatch.setattr(queries, "get_projection_mgr", lambda: manager)
    monkeypatch.setattr(_wiring, "get_projection_mgr", lambda: manager)


async def _listed(review_verdict: ReviewVerdict | None) -> dict[str, str | None]:
    """`GET /executions?review_verdict=...`, as execution id -> the verdict on the wire."""
    from syn_api.routes.executions import queries

    # Every parameter explicit: called outside FastAPI, `Query(...)` defaults
    # arrive as `Query` objects rather than the values they describe.
    response = await queries.list_executions_endpoint(
        status=None,
        statuses=None,
        started_after=None,
        started_before=None,
        q=None,
        tag=None,
        eval_id=None,
        in_eval=None,
        review_verdict=review_verdict,
        page=1,
        page_size=50,
    )
    assert response.total == len(response.executions)
    return {
        e.workflow_execution_id: e.model_dump(mode="json")["review_verdict"]
        for e in response.executions
    }


class TestTheListCarriesTheVerdict:
    @pytest.mark.asyncio
    async def test_each_row_carries_its_verdict(self, monkeypatch: pytest.MonkeyPatch) -> None:
        await _serve(monkeypatch)
        assert await _listed(None) == {
            "exec-certified-1630": "certified",
            "exec-blocked-1630": "blocked",
            "exec-unreviewed-1630": None,
        }

    @pytest.mark.asyncio
    async def test_the_list_and_the_detail_agree(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from syn_api.routes.executions import queries

        await _serve(monkeypatch)
        listed = await _listed(None)
        for execution_id in VERDICTS:
            detail = await queries.get_execution_endpoint(execution_id)
            assert detail.model_dump(mode="json")["review_verdict"] == listed[execution_id]


class TestTheVerdictFilter:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("verdict", "expected"),
        [
            (ReviewVerdict.CERTIFIED, "exec-certified-1630"),
            (ReviewVerdict.BLOCKED, "exec-blocked-1630"),
        ],
    )
    async def test_a_verdict_keeps_only_runs_that_completed_on_it(
        self, monkeypatch: pytest.MonkeyPatch, verdict: ReviewVerdict, expected: str
    ) -> None:
        await _serve(monkeypatch)
        assert set(await _listed(verdict)) == {expected}
