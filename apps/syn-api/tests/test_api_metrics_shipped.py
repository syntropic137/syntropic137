"""GET /metrics/shipped: the wire contract of the "Shipped by agents" block."""

from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from syn_domain.contexts.orchestration.domain.read_models.workflow_execution_summary import (
    WorkflowExecutionSummary,
)
from syn_domain.contexts.orchestration.slices.shipped_metrics import (
    CommitSighting,
    ShippedMetricsQueryService,
)

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping, Sequence

pytestmark = [pytest.mark.unit]

TODAY = date(2026, 10, 9)


class _Sightings:
    async def sightings(self, since: datetime, until: datetime) -> list[CommitSighting]:
        return [CommitSighting("a", "e1", TODAY), CommitSighting("b", "e1", date(2026, 9, 20))]


class _Executions:
    async def by_ids(self, execution_ids: Sequence[str]) -> Mapping[str, WorkflowExecutionSummary]:
        return {
            "e1": WorkflowExecutionSummary(
                workflow_execution_id="e1",
                workflow_id="wf",
                workflow_name="Implement",
                status="completed",
                started_at=None,
                completed_at=None,
                completed_phases=1,
                total_phases=1,
                total_tokens=0,
                repos=("https://github.com/acme/api",),
            )
        }


class _Boom(Exception):
    pass


async def _connected() -> None:
    return None


@pytest.fixture
def client() -> Iterator[TestClient]:
    from syn_api.routes import metrics

    app = FastAPI()
    app.include_router(metrics.router)
    service = ShippedMetricsQueryService(_Sightings(), _Executions(), today=lambda: TODAY)
    with (
        patch.object(metrics, "ensure_connected", _connected),
        patch.object(metrics, "get_shipped_metrics_query", lambda: service),
    ):
        yield TestClient(app)


def test_contract_shape(client: TestClient) -> None:
    body = client.get("/metrics/shipped").json()
    assert body["window"] == {"days": 14, "from": "2026-09-26", "to": "2026-10-09"}
    assert body["previous"] == {"from": "2026-09-12", "to": "2026-09-25"}
    commits = body["commits"]
    assert (commits["total"], commits["previous_total"], commits["delta"]) == (1, 1, 0)
    assert (commits["delta_display"], commits["delta_unit"]) == ("0%", "percent")
    assert len(commits["series"]) == 14
    assert commits["series"][-1] == {"date": "2026-10-09", "value": 1}
    assert body["repos"] == ["acme/api"]
    assert body["repos_touched"]["delta_unit"] == "count"
    assert body["by_workflow"] == [
        {"workflow_id": "wf", "workflow_name": "Implement", "commits": 1, "repos_touched": 1}
    ]
    for name in ("prs_opened", "prs_merged", "merge_rate"):
        assert body[name]["total"] is None
        assert body[name]["reason"]
    assert body["unavailable"] == ["prs_opened", "prs_merged", "merge_rate"]


def test_workflow_filter_drops_by_workflow(client: TestClient) -> None:
    body = client.get("/metrics/shipped", params={"days": 7, "workflow_id": "wf"}).json()
    assert body["window"]["days"] == 7
    assert body["workflow_id"] == "wf"
    assert body["by_workflow"] is None


@pytest.mark.parametrize("days", [1, 13, 31])
def test_other_windows_are_refused(client: TestClient, days: int) -> None:
    assert client.get("/metrics/shipped", params={"days": days}).status_code == 422


@pytest.mark.asyncio
async def test_a_store_failure_is_503_not_zero() -> None:
    from syn_api.routes import metrics

    with (
        patch.object(metrics, "ensure_connected", _connected),
        patch.object(metrics, "get_shipped_metrics_query", side_effect=_Boom("db down")),
        pytest.raises(HTTPException) as caught,
    ):
        await metrics.get_shipped_metrics_endpoint(days=14, workflow_id=None)
    assert caught.value.status_code == 503
