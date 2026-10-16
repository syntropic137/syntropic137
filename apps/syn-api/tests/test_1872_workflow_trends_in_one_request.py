"""GET /workflows/trends answers every card on the Workflows page in one request (#1872).

The page used to call ``GET /workflows/{id}/trend`` once per card, so its
request count grew with the catalogue and the gateway answered 429. One
request now carries every requested workflow's latest runs, and the Lane 2
reads behind it stay batched however many workflows it names.
"""

from __future__ import annotations

import os

os.environ.setdefault("APP_ENVIRONMENT", "test")

from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from httpx import ASGITransport, AsyncClient

from syn_domain.contexts.agent_sessions.domain.read_models.session_cost import SessionCost
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

    from syn_api.types import WorkflowTrendPointResponse

pytestmark = [pytest.mark.unit, pytest.mark.anyio]

OPUS = "claude-opus-5-5"
# Run count per workflow: distinct, so a point attributed to the wrong workflow shows.
RUNS = {"wf-a": 3, "wf-b": 5, "wf-c": 0}


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

    def _cost(self, execution_id: str) -> ExecutionCost:
        return ExecutionCost(
            execution_id=execution_id,
            total_cost_usd=Decimal("0.5"),
            input_tokens=1,
            output_tokens=1,
        )

    async def get_session_costs(self, session_ids: Sequence[str]) -> dict[str, SessionCost]:
        self.calls += 1
        return {
            s: SessionCost(session_id=s, agent_model=OPUS, requested_model="opus")
            for s in session_ids
        }

    async def list_costs_for_ids(self, execution_ids: list[str]) -> ExecutionCostsForIds:
        self.calls += 1
        return ExecutionCostsForIds(costs=[self._cost(e) for e in execution_ids], tool_calls={})


@pytest.fixture
async def lane2(monkeypatch: pytest.MonkeyPatch) -> _Lane2:
    from syn_api._wiring import ensure_connected, get_projection_mgr

    await ensure_connected()
    fake = _Lane2()
    manager = get_projection_mgr()
    monkeypatch.setattr(
        manager.session_cost, "get_session_costs", fake.get_session_costs, raising=False
    )
    monkeypatch.setattr(manager.execution_cost, "list_costs_for_ids", fake.list_costs_for_ids)
    return fake


@pytest.fixture
async def client(lane2: _Lane2) -> AsyncIterator[AsyncClient]:
    from syn_api.main import create_app

    async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://t") as c:
        yield c


async def _seed() -> None:
    from syn_api._wiring import get_projection_mgr

    store = get_projection_mgr().store
    for workflow_id, runs in RUNS.items():
        workflow = WorkflowDetail(
            id=workflow_id,
            name=workflow_id,
            workflow_type="research",
            classification="simple",
            description=None,
        )
        await store.save("workflow_details", workflow_id, workflow.to_dict())
        for r in range(runs):
            execution_id = f"{workflow_id}-exec-{r}"
            started = f"2026-10-02T10:{r:02d}:00+00:00"
            # Each run of wf-b takes 10s longer than the last; wf-a's take 7s.
            seconds = (10 if workflow_id == "wf-b" else 7) * (r + 1)
            completed = f"2026-10-02T10:{r:02d}:{seconds:02d}+00:00"
            common = {
                "workflow_execution_id": execution_id,
                "workflow_id": workflow_id,
                "workflow_name": workflow_id,
                "status": "completed",
                "started_at": started,
                "completed_at": completed,
            }
            summary = WorkflowExecutionSummary(
                **common, completed_phases=1, total_phases=1, total_tokens=0
            )
            await store.save("workflow_executions", execution_id, summary.to_dict())
            detail = WorkflowExecutionDetail(
                **common,
                phases=(
                    PhaseExecutionDetail(
                        workflow_phase_id="p0",
                        name="phase 0",
                        status="completed",
                        session_id=f"sess-{execution_id}",
                        started_at=started,
                        completed_at=completed,
                    ),
                ),
            )
            await store.save("workflow_execution_details", execution_id, detail.to_dict())


async def test_one_request_returns_every_workflows_trend_points(
    client: AsyncClient, lane2: _Lane2
) -> None:
    await _seed()
    lane2.calls = 0

    response = await client.get(
        "/workflows/trends", params={"ids": "wf-b,wf-a,wf-c", "page_size": 12}
    )

    assert response.status_code == 200, response.text
    trends = response.json()["trends"]
    # In the order asked, each with its own runs and nothing else's.
    assert [t["workflow_id"] for t in trends] == ["wf-b", "wf-a", "wf-c"]
    by_id = {t["workflow_id"]: t for t in trends}
    assert by_id["wf-b"]["total"] == 5
    assert {i["execution_id"] for i in by_id["wf-b"]["items"]} == {
        f"wf-b-exec-{r}" for r in range(5)
    }
    assert sorted(i["duration_seconds"] for i in by_id["wf-b"]["items"]) == [
        10.0,
        20.0,
        30.0,
        40.0,
        50.0,
    ]
    assert sorted(i["duration_seconds"] for i in by_id["wf-a"]["items"]) == [7.0, 14.0, 21.0]
    assert by_id["wf-c"]["items"] == [] and by_id["wf-c"]["total"] == 0
    # Every point of every workflow carries the display strings, formatted from its own run.
    for trend in trends:
        for point in trend["items"]:
            assert point["execution_id"].startswith(f"{trend['workflow_id']}-exec-")
            assert point["date"] and point["status"] == "completed"
            assert point["duration_display"] == f"{int(point['duration_seconds'])}s", point
            assert point["cost_display"] == "$0.50", point
    # The card's trend label, formatted here: the UI renders it and computes no words.
    assert by_id["wf-b"]["duration_trend"] == {
        "kind": "slower",
        "pct": 400,
        "runs": 5,
        "word_display": "Slower",
        "sub_display": "+400% time, last 5",
        "label_display": "Duration trend: 400% slower over the last 5 runs",
    }
    assert by_id["wf-a"]["duration_trend"]["sub_display"] == "+200% time, last 3"
    assert by_id["wf-c"]["duration_trend"] == {
        "kind": "none",
        "pct": 0,
        "runs": 0,
        "word_display": "No runs yet",
        "sub_display": "\u2014",
        "label_display": "No runs yet",
    }
    # Two Lane 2 reads for the whole batch, never two per workflow.
    assert lane2.calls <= 2, f"{lane2.calls} Lane 2 round trips for one batch"


async def test_each_entry_matches_the_single_workflow_trend(client: AsyncClient) -> None:
    await _seed()

    batch = (
        await client.get("/workflows/trends", params={"ids": "wf-a,wf-b", "page_size": 2})
    ).json()
    assert [e["workflow_id"] for e in batch["trends"]] == ["wf-a", "wf-b"]
    for entry in batch["trends"]:
        single = await client.get(
            f"/workflows/{entry['workflow_id']}/trend", params={"page_size": 2}
        )
        assert len(entry["items"]) == 2
        # The batch adds the card's label; everything else is the single endpoint's answer.
        assert {k: v for k, v in entry.items() if k != "duration_trend"} == single.json()


async def test_unknown_ids_are_left_out_not_fatal(client: AsyncClient) -> None:
    await _seed()

    response = await client.get("/workflows/trends", params={"ids": "wf-a,no-such-workflow,wf-a"})

    assert response.status_code == 200, response.text
    assert [t["workflow_id"] for t in response.json()["trends"]] == ["wf-a"]


async def test_more_ids_than_a_page_is_refused(client: AsyncClient) -> None:
    from syn_api.list_query import MAX_PAGE_SIZE

    ids = ",".join(f"wf-{i}" for i in range(MAX_PAGE_SIZE + 1))

    response = await client.get("/workflows/trends", params={"ids": ids})

    assert response.status_code == 422


def _point(
    day: int, seconds: float | None, *, lower_bound: bool = False
) -> WorkflowTrendPointResponse:
    from syn_api.types import WorkflowTrendPointResponse

    return WorkflowTrendPointResponse(
        execution_id=f"x-{day}",
        date=f"2026-10-{day:02d}T00:00:00Z",
        status="completed",
        workflow_version=None,
        cost_usd=None,
        cost_is_lower_bound=False,
        cost_display="$0.00",
        duration_seconds=seconds,
        duration_is_lower_bound=lower_bound,
        duration_display="",
        tokens=0,
        phase_durations=[],
    )


@pytest.mark.parametrize(
    ("durations", "runs_count", "expected"),
    [
        # Newest first, as the API sends them; the fit reads them oldest first.
        ([100, 120, 144], 3, ("faster", "Faster", "\u221231% time, last 3")),
        ([100, 102, 101], 3, ("steady", "Steady", "\u00b11% time, last 3")),
        ([100, 50], 2, ("few", "Too few runs", "2 runs")),
        ([], 4, ("none", "No trend", "\u2014")),
    ],
)
def test_the_card_label_is_classified_here(
    durations: list[float], runs_count: int, expected: tuple[str, str, str]
) -> None:
    from syn_api.routes.trends import duration_trend

    points = [_point(len(durations) - i, d) for i, d in enumerate(durations)]

    summary = duration_trend(points, runs_count)

    assert (summary.kind, summary.word_display, summary.sub_display) == expected


def test_a_lower_bound_duration_is_not_measured() -> None:
    from syn_api.routes.trends import duration_trend

    points = [_point(3, 999, lower_bound=True), _point(2, 50), _point(1, 50)]

    summary = duration_trend(points, 3)

    assert (summary.kind, summary.runs, summary.sub_display) == ("few", 2, "2 runs")
