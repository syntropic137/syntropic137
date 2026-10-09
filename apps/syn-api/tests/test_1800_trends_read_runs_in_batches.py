"""Both trend endpoints read a page of runs in a fixed number of batches (#1800 review).

The workflow trend used to call ``get_detail`` per row, and each call loaded
the execution detail, the execution's Lane 2 cost and one Lane 2 session cost
per phase: a 50-row page was 50 full execution loads and ~150 Lane 2 round
trips. Both trends now read through the batched ``RunReads`` (#1811), so a
page costs one session-cost read and one execution-cost read whatever its size.
"""

from __future__ import annotations

import os

os.environ.setdefault("APP_ENVIRONMENT", "test")

from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from httpx import ASGITransport, AsyncClient

from syn_domain.contexts.agent_sessions.domain.read_models.session_cost import SessionCost
from syn_domain.contexts.orchestration.domain.read_models.eval_summary import EvalRecord
from syn_domain.contexts.orchestration.domain.read_models.execution_cost import ExecutionCost
from syn_domain.contexts.orchestration.domain.read_models.workflow_detail import WorkflowDetail
from syn_domain.contexts.orchestration.domain.read_models.workflow_execution_detail import (
    PhaseExecutionDetail,
    WorkflowExecutionDetail,
)
from syn_domain.contexts.orchestration.domain.read_models.workflow_execution_summary import (
    WorkflowExecutionSummary,
)
from syn_domain.contexts.orchestration.slices.execution_cost.query_service import (
    ExecutionCostsForIds,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator, Sequence

pytestmark = [pytest.mark.unit, pytest.mark.anyio]

RUNS = 50
PHASES_PER_RUN = 3
WORKFLOW = "wf-trend-batch"
EVAL = "eval-trend-batch"
OPUS = "claude-opus-5-5"


@pytest.fixture(autouse=True)
def _reset_storage() -> Iterator[None]:
    from syn_adapters.projection_stores import get_projection_store
    from syn_adapters.projections.manager import reset_projection_manager
    from syn_adapters.storage import reset_storage

    reset_storage()
    reset_projection_manager()
    store = get_projection_store()
    if hasattr(store, "_data"):
        store._data.clear()  # pyright: ignore[reportAttributeAccessIssue]  # in-memory store only
    if hasattr(store, "_state"):
        store._state.clear()  # pyright: ignore[reportAttributeAccessIssue]  # in-memory store only
    yield
    reset_storage()
    reset_projection_manager()


class _Lane2:
    """The Lane 2 cost reads, each call counted as one round trip."""

    def __init__(self) -> None:
        self.calls = 0

    def _session(self, session_id: str) -> SessionCost:
        return SessionCost(session_id=session_id, agent_model=OPUS, requested_model="opus")

    def _cost(self, execution_id: str) -> ExecutionCost:
        return ExecutionCost(
            execution_id=execution_id,
            total_cost_usd=Decimal("1.25"),
            input_tokens=10,
            output_tokens=10,
        )

    async def get_session_cost(self, session_id: str) -> SessionCost | None:
        self.calls += 1
        return self._session(session_id)

    async def get_session_costs(self, session_ids: Sequence[str]) -> dict[str, SessionCost]:
        self.calls += 1
        return {sid: self._session(sid) for sid in session_ids}

    async def get_execution_cost(self, execution_id: str) -> ExecutionCost | None:
        self.calls += 1
        return self._cost(execution_id)

    async def list_costs_for_ids(self, execution_ids: list[str]) -> ExecutionCostsForIds:
        self.calls += 1
        return ExecutionCostsForIds(costs=[self._cost(e) for e in execution_ids], tool_calls={})


@pytest.fixture
async def lane2(monkeypatch: pytest.MonkeyPatch) -> _Lane2:
    from syn_api._wiring import ensure_connected, get_projection_mgr

    await ensure_connected()
    fake = _Lane2()
    manager = get_projection_mgr()
    for name in ("get_session_cost", "get_session_costs"):
        monkeypatch.setattr(manager.session_cost, name, getattr(fake, name), raising=False)
    for name in ("get_execution_cost", "list_costs_for_ids"):
        monkeypatch.setattr(manager.execution_cost, name, getattr(fake, name))
    return fake


@pytest.fixture
async def client(lane2: _Lane2) -> AsyncIterator[AsyncClient]:
    from syn_api.main import create_app

    async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://t") as c:
        yield c


async def _seed() -> None:
    """One workflow and one eval, 50 three-phase runs of it, written into the read models."""
    from syn_api._wiring import get_projection_mgr

    store = get_projection_mgr().store
    workflow = WorkflowDetail(
        id=WORKFLOW, name="wf", workflow_type="research", classification="simple", description=None
    )
    await store.save("workflow_details", WORKFLOW, workflow.to_dict())
    record = EvalRecord(eval_id=EVAL, name="e", goal="g", created_at="2026-10-01T00:00:00Z")
    await store.save("evals", EVAL, record.model_dump(mode="json"))
    for r in range(RUNS):
        execution_id = f"exec-{r:03d}"
        started = f"2026-10-02T{r // 60:02d}:{r % 60:02d}:00+00:00"
        completed = f"2026-10-02T{r // 60:02d}:{r % 60:02d}:30+00:00"
        summary = WorkflowExecutionSummary(
            workflow_execution_id=execution_id,
            workflow_id=WORKFLOW,
            workflow_name="wf",
            status="completed",
            started_at=started,
            completed_at=completed,
            completed_phases=PHASES_PER_RUN,
            total_phases=PHASES_PER_RUN,
            total_tokens=0,
            eval_id=EVAL,
            association_kind="launched",
            workflow_version="1",
        )
        await store.save("workflow_executions", execution_id, summary.to_dict())
        detail = WorkflowExecutionDetail(
            workflow_execution_id=execution_id,
            workflow_id=WORKFLOW,
            workflow_name="wf",
            status="completed",
            started_at=started,
            completed_at=completed,
            phases=tuple(
                PhaseExecutionDetail(
                    workflow_phase_id=f"p{p}",
                    name=f"phase {p}",
                    status="completed",
                    session_id=f"sess-{execution_id}-{p}",
                    started_at=started,
                    completed_at=completed,
                )
                for p in range(PHASES_PER_RUN)
            ),
        )
        await store.save("workflow_execution_details", execution_id, detail.to_dict())


@pytest.mark.parametrize("path", [f"/workflows/{WORKFLOW}/trend", f"/evals/{EVAL}/trend"])
async def test_a_trend_page_of_50_runs_costs_two_lane2_round_trips(
    client: AsyncClient, lane2: _Lane2, path: str
) -> None:
    await _seed()
    lane2.calls = 0

    response = await client.get(path, params={"page_size": RUNS})

    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert len(items) == RUNS
    assert {item["cost_usd"] for item in items} == {"1.25"}
    assert all(item["duration_seconds"] == 90.0 for item in items)
    # One session-cost read and one execution-cost read for the page: never
    # one per run (50) or per phase (150).
    assert lane2.calls <= 2, f"{lane2.calls} Lane 2 round trips for one trend page"


async def test_a_workflow_trend_point_carries_each_phase_duration(
    client: AsyncClient, lane2: _Lane2
) -> None:
    await _seed()

    body = (await client.get(f"/workflows/{WORKFLOW}/trend", params={"page_size": 1})).json()

    [point] = body["items"]
    assert point["execution_id"] == f"exec-{RUNS - 1:03d}"
    assert [(p["phase_id"], p["duration_seconds"]) for p in point["phase_durations"]] == [
        (f"p{p}", 30.0) for p in range(PHASES_PER_RUN)
    ]
